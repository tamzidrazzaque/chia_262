"""Coordinated BOOM allocation/branch profiles and measured-feedback proposals."""

import hashlib
import json
import os
from pathlib import Path

from chia.chipyard.boom_model import SEED_COSTS, validate_move_profile
from chia.chipyard.cost_model import validate_costs
from chia.models.claude import ClaudeCodeLLM


def validate(value):
    if not isinstance(value, dict) or value.keys() != {"costs", "move_profile", "rationale"}:
        raise ValueError("expected costs, move_profile, rationale")
    validate_costs(value["costs"])
    validate_move_profile(value["move_profile"])
    if not isinstance(value["rationale"], str) or not value["rationale"].strip() or len(value["rationale"]) > 8000:
        raise ValueError("require a bounded explanation")
    return value


def identity(value):
    return hashlib.sha256(json.dumps({k: value[k] for k in ("costs", "move_profile")}, sort_keys=True).encode()).hexdigest()


def seed_profiles():
    def profile(branch, memory, transfer, load, store, to_fp, to_gpr, fp_load, fp_store, rationale):
        return validate({"costs": {**SEED_COSTS, "branch_cost": branch, "memory_cost": memory, "fmv_cost": transfer},
            "move_profile": {"gpr_to_fpr": to_fp, "fpr_to_gpr": to_gpr, "gpr_load": load,
                             "gpr_store": store, "fpr_load": fp_load, "fpr_store": fp_store},
            "rationale": rationale})
    return [
        profile(3, 6, 16, 6, 6, 16, 16, 6, 6,
                "Integer-register residency: discourage cross-file moves in both directions while making spills moderately expensive. "
                "Test whether avoiding transfer-heavy allocation recovers Exchange2 opportunities beyond the scalar FMV threshold."),
        profile(6, 4, 12, 3, 3, 12, 12, 4, 4,
                "L1-spill alternative: prefer explicit stack loads/stores over FP-register parking, paired with a higher branch cost. "
                "This deliberately explores a different allocation/branch regime, not a one-unit scalar adjustment."),
        profile(4, 8, 10, 8, 5, 6, 12, 8, 5,
                "Directional allocation: expensive reloads and FP-to-integer moves, less expensive integer-to-FP moves/stores. "
                "Tests the interaction between live-range placement and asymmetric crossing/spilling costs; heuristic values are uncalibrated."),
        profile(8, 7, 16, 8, 6, 16, 16, 10, 8,
                "Branch/register-pressure regime: strong branch cost and high cross-file/reload costs jointly reshape allocation and if-conversion. "
                "Accept only correct distinct application code and measure against the original compiler."),
    ]


def feedback_proposal(config, history, prior, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    prompt = {"goal": "Substantially improve the configured SPEC train workload on the fixed MegaBOOM V3 F2 target",
        "hardware": {"decode_retire_width": 4, "integer_memory_fp_issue": [4, 2, 2], "ROB_entries": 128,
                     "integer_multiply_scheduler_latency": 3, "fp_fma_scheduler_latency": 4},
        "constraints": "Return costs, move_profile, rationale JSON only. Costs are heuristic compiler costs, not measured cycles. "
            "Keep ISA/ABI, compiler revision, -O3/static flags and scheduler structure fixed. Costs integers1..64, move-profile integers1..32. "
            "Optimize jointly: register allocation, stack reload/store tradeoffs, directional GPR/FP moves and branch conversion. "
            "Exchange2 uses integer arrays/recursion, not floating-point arithmetic. Low scalar FMV=4 previously regressed it. "
            "Do not repeat a tested profile. Explain expected generated-code change and what would falsify it. "
            "Only native-correct F2 train timings guide selection; reference inputs are held out. "
            "Generic microkernel predictions failed validation and must not rank this campaign.",
        "target_benchmarks": config["benchmarks"], "history": history, "prior_train_evidence": prior,
        "response_format": seed_profiles()[0]}
    (directory / "prompt.json").write_text(json.dumps(prompt, indent=2) + "\n")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    llm = ClaudeCodeLLM(backend="cli", model=config["model"], resume_session=False,
        projects_cwd=None, dangerously_skip_permissions=False,
        extra_cli_args=["--tools", "", "--strict-mcp-config"], retries=1,
        log_dir=str(directory / "claude"), timeout_seconds=600,
        system_message="Propose coordinated BOOM compiler costs from measured train feedback. JSON only. No tools.")
    result = llm.prompt(json.dumps(prompt), tools=[])
    (directory / "response.txt").write_text(result.result)
    if not result.success:
        raise RuntimeError("Claude campaign proposal failed; inspect saved CLI logs")
    text = result.result.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    return validate(json.loads(text))
