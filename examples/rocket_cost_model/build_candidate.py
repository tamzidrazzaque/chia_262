"""Build one bounded Rocket scalar-cost proposal using the prepared GCC tree.

This stage executes no workloads and cannot accept a candidate as a winner.
"""

import argparse
import json
from pathlib import Path

from chia.chipyard.cost_model import build_compiler, validate_costs


def validate_proposal(value):
    """Require a complete bounded table, a code-change hypothesis and a falsifier."""
    if not isinstance(value, dict) or value.keys() != {"costs", "hypothesis", "falsifier"}:
        raise ValueError("expected costs, hypothesis and falsifier only")
    validate_costs(value["costs"])
    for key in ("hypothesis", "falsifier"):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 8000:
            raise ValueError("require a bounded nonempty " + key)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proposal = validate_proposal(json.loads(args.proposal.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n")
    record = build_compiler(str(args.root.resolve()), str(args.baseline_prefix.resolve()),
                            proposal["costs"], tuning="rocket")
    (args.output / "compiler.json").write_text(json.dumps(record, indent=2) + "\n")
    print(args.output / "compiler.json")


if __name__ == "__main__":
    main()
