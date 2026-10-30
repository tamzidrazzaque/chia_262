"""Choose a bounded next BOOM proposal from measured hardware observations."""

import argparse
import copy
import json
from pathlib import Path

from chia.chipyard.boom_model import SEED_COSTS
from chia.chipyard.tuning_search import suggest


def proposal_pool():
    seed = {"costs": SEED_COSTS, "tuning": "boom", "scheduling": {"issue_rate": 4}}
    pool = [copy.deepcopy(seed)]
    for key, values in (("memory_cost", (3, 4, 6, 7)), ("branch_cost", (2, 4, 5)),
                        ("fmv_cost", (4, 6, 10))):
        for value in values:
            p = copy.deepcopy(seed)
            p["costs"][key] = value
            pool.append(p)
    for value in (2, 3):
        p = copy.deepcopy(seed)
        p["scheduling"]["issue_rate"] = value
        pool.append(p)
    return pool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", type=int, default=0)
    args = parser.parse_args()
    data = json.loads(args.evidence.read_text())
    result = suggest(proposal_pool(), data["observations"], args.step)
    result["required_gates"] = ["immutable compiler snapshot", "QEMU independent checksum",
                               "paired F2 measurement", "SPEC train transfer", "held-out SPEC ref"]
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
