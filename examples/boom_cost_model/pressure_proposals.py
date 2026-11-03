"""Evidence-guided BOOM policy search with frozen incumbent scalar costs."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from chia.chipyard.boom_model import GROWTH_PRESETS, normalize_policy, validate_policy
from chia.models.claude import ClaudeCodeLLM
from examples.boom_cost_model import campaign_proposals


ANCHOR_COSTS = {"fp_add": [4, 4], "fp_mul": [4, 4], "fp_div": [20, 20],
    "int_mul": [4, 4], "int_div": [6, 6], "branch_cost": 8, "memory_cost": 7, "fmv_cost": 16}
ANCHOR_MOVES = {"gpr_to_fpr": 16, "fpr_to_gpr": 16, "gpr_load": 8,
    "gpr_store": 6, "fpr_load": 10, "fpr_store": 8}


def validate_profile(value, growth_choices):
    """Only bounded policies may vary; preserve the measured incumbent costs."""
    if not isinstance(value, dict) or value.keys() != {"costs", "move_profile", "policy", "rationale"}:
        raise ValueError("expected costs, move_profile, policy and rationale")
    campaign_proposals.validate({k: value[k] for k in ("costs", "move_profile", "rationale")})
    validate_policy(value["policy"])
    if value["policy"]["growth_budget"] not in growth_choices:
        raise ValueError("growth preset is outside this campaign")
    if value["costs"] != ANCHOR_COSTS or value["move_profile"] != ANCHOR_MOVES:
        raise ValueError("pressure campaign freezes the incumbent scalar/move costs")
    return value


def validate(value):
    return validate_profile(value, ("default", "compact"))


def identity(value):
    validate(value)
    return profile_identity(value)


def profile_identity(value):
    """Identify an already validated profile without paths or rationale."""
    return hashlib.sha256(json.dumps({"costs": value["costs"], "move_profile": value["move_profile"],
        "policy": normalize_policy(value["policy"])}, sort_keys=True).encode()).hexdigest()


def seed_profiles():
    """Incumbent, pressure only, compact only and their interaction."""
    definitions = [
        (0, False, "default", "Fresh incumbent control: exact historical candidate 3 snapshot; no policy overrides."),
        (2, True, "default", "Enable model-based pressure-aware scheduling and IRA loop-pressure estimates. Test allocation/live-range choices without reducing loop-growth defaults."),
        (0, False, "compact", "Limit complete-peel instruction budget to 64 and unroll-and-jam factor to 1. Test whether less expansion reduces pressure and code footprint while retaining the incumbent scheduling policy."),
        (2, True, "compact", "Combine pressure-aware scheduling/allocation with bounded loop growth. Test their interaction; high static IRA pressure motivates the hypothesis but does not establish dynamic spill cost."),
    ]
    return [validate({"costs": deepcopy(ANCHOR_COSTS), "move_profile": dict(ANCHOR_MOVES),
        "policy": {"pressure_algorithm": algorithm, "ira_loop_pressure": ira, "growth_budget": growth},
        "rationale": rationale}) for algorithm, ira, growth, rationale in definitions]


def feedback_proposal(config, history, prior, directory: Path, *, example=None, validator=None,
                      growth_choices=("default", "compact")):
    """Authenticated CLI chooses an untested policy using measured train evidence."""
    directory.mkdir(parents=True, exist_ok=True)
    prompt = {"goal": "Improve real Exchange2 train execution on the fixed MegaBOOM F2 target beyond the original GCC and incumbent.",
        "constraints": "Return exactly the example schema as JSON. Keep costs/move_profile frozen. Only policy varies: "
            "pressure_algorithm in [0,1,2], ira_loop_pressure boolean, growth_budget in " + json.dumps(growth_choices) + ". "
            "Algorithm 0 keeps the original pressure default; 1/2 enable GCC weighted/model pressure algorithms. "
            "Compact uses complete-peel budget64 and unroll/jam factor1 rather than defaults200/4. "
            "These are experimental target defaults, not measured hardware costs. All command-line baseline flags, "
            "source revision, ISA/ABI, libraries and FPGA image remain fixed. Never repeat a measured or pending policy. "
            "Explain expected code change and falsification. No tools, patches or commands. Reference inputs are held out. "
            "Static pressure and functional call counts do not identify cycle bottlenecks. No application cross-file moves "
            "were present, including the earlier FMV=4 regression; do not invent a register-parking explanation. "
            "The solver is mostly integer but MAIN contains some floating operations. Generic microkernel ranks are unvalidated.",
        "analysis_evidence": config.get("analysis_evidence", {}), "history": history,
        "prior_train_evidence": prior, "example": example or seed_profiles()[0],
        "growth_presets": {name: GROWTH_PRESETS[name] for name in growth_choices},
        "incremental_promotion_margin": config.get("min_incremental_improvement")}
    return request_json(config, prompt, directory, validator or validate)


def request_json(config, prompt, directory: Path, validator):
    """Use authenticated Claude CLI with data-only output and no executable tools."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "prompt.json").write_text(json.dumps(prompt, indent=2) + "\n")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    cli_args = ["--tools", "", "--strict-mcp-config"]
    effort = config.get('llm_effort')
    if effort is not None:
        if effort not in ('low','medium','high','xhigh','max'):
            raise ValueError('unsupported Claude CLI effort')
        cli_args += ['--effort',effort]
    (directory / 'llm-settings.json').write_text(json.dumps({'backend':'cli','model':config['model'],
        'effort':effort or 'inherit-cli-settings','tools_enabled':False},indent=2)+'\n')
    llm = ClaudeCodeLLM(backend="cli", model=config["model"], resume_session=False,
        projects_cwd=None, dangerously_skip_permissions=False,
        extra_cli_args=cli_args, retries=1,
        log_dir=str(directory / "claude"), timeout_seconds=600,
        system_message="Choose an evidence-guided bounded BOOM compiler profile. JSON only; no tools.")
    result = llm.prompt(json.dumps(prompt), tools=[])
    (directory / "response.txt").write_text(result.result)
    if not result.success:
        raise RuntimeError("Claude pressure proposal failed; inspect saved CLI logs")
    text = result.result.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    return validator(json.loads(text))
