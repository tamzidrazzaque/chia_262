"""Have authenticated Claude choose a bounded, falsifiable hardware experiment."""

import argparse
import json
import os
from pathlib import Path

from chia.chipyard.tuning_search import features, suggest
from chia.models.claude import ClaudeCodeLLM
from examples.boom_cost_model.suggest_next import proposal_pool


def compact_evidence(evidence):
    """Send measured settings and changed opcodes, not full assembly features."""
    summary = {k: v for k, v in evidence.items() if k != "observations"}
    baseline = next(o for o in evidence["observations"] if o["speedup"] == 1.0)
    base_features = baseline.get("assembly_features", {})
    observations = []
    for o in evidence["observations"]:
        record = {k: v for k, v in o.items() if k != "assembly_features"}
        differences = {}
        for function, data in o.get("assembly_features", {}).items():
            if function not in ("stream", "branch", "pointer", "multiply", "divide", "floating"):
                continue
            old = base_features.get(function, {}).get("opcode_counts", {})
            counts = data["opcode_counts"]
            delta = {op: counts.get(op, 0) - old.get(op, 0) for op in counts.keys() | old.keys()
                     if counts.get(op, 0) != old.get(op, 0)}
            if delta:
                differences[function] = delta
        record["changed_opcode_counts"] = differences
        observations.append(record)
    summary["observations"] = observations
    return summary


def parse_choice(text, pool):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    value = json.loads(text)
    if not isinstance(value, dict) or value.keys() != {"candidate_index", "hypothesis", "falsifier"}:
        raise ValueError("expected candidate_index, hypothesis, falsifier")
    if type(value["candidate_index"]) is not int or not 0 <= value["candidate_index"] < len(pool):
        raise ValueError("candidate index outside bounded pool")
    if any(not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > 4000
           for k in ("hypothesis", "falsifier")):
        raise ValueError("invalid experiment explanation")
    return {**value, "proposal": pool[value["candidate_index"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--pending-compiler", type=Path, action="append", default=[],
                        help="Exclude immutable snapshots already queued or running")
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.config.read_text())
    evidence = json.loads(args.evidence.read_text())
    tested = {features(o["proposal"]) for o in evidence["observations"]}
    for filename in args.pending_compiler:
        pending = json.loads(filename.read_text())
        tested.add(features({"costs": pending["costs"], "tuning": pending.get("tuning", "rocket"),
                             "scheduling": pending.get("scheduling", {"issue_rate": 4 if pending.get("tuning") == "boom" else 1})}))
    pool = [p for p in proposal_pool() if features(p) not in tested]
    recommendation = suggest(pool, evidence["observations"])
    prompt = {"goal": "Choose the next informative compiler experiment for the fixed MegaBOOM V3 F2 target",
              "constraints": "Choose one candidate_index from this bounded pool. No shell/tools. Original baseline and ISA fixed. "
                             "Kernel wins are not SPEC wins. Treat failed predictive validation as untrusted. "
                             "Exchange2 is an integer Sudoku solver written in Fortran, not an FP workload. "
                             "Reference inputs are held out. Favor source/calibration evidence and a falsifiable hypothesis.",
              "hardware_evidence": compact_evidence(evidence), "programmatic_recommendation": recommendation, "pool": pool,
              "response_format": {"candidate_index": 0, "hypothesis": "what this changes and why",
                                  "falsifier": "which measured result would reject the hypothesis"}}
    (args.run_dir / "prompt.json").write_text(json.dumps(prompt, indent=2) + "\n")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    llm = ClaudeCodeLLM(backend="cli", model=config["model"], resume_session=False,
        projects_cwd=None, dangerously_skip_permissions=False,
        extra_cli_args=["--tools", "", "--strict-mcp-config"], retries=1,
        log_dir=str(args.run_dir / "claude"), timeout_seconds=600,
        system_message="Select a bounded experiment using measured evidence. Return JSON only; do not use tools.")
    response = llm.prompt(json.dumps(prompt), tools=[])
    (args.run_dir / "response.txt").write_text(response.result)
    if not response.success:
        raise RuntimeError("Claude proposal failed; inspect private logs")
    result = parse_choice(response.result, pool)
    result["surrogate_validation"] = recommendation["validation"]
    (args.run_dir / "proposal.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.run_dir / "costs.json").write_text(json.dumps(result["proposal"]["costs"], indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
