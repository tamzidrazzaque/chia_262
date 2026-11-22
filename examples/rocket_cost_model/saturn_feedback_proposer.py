"""Bounded feedback proposer for the Saturn cost-model search.

This process never builds or dispatches hardware work.  It watches the private
controller state and adds at most one new proposal per completed, measured
candidate when the pending queue is below a configured bound.  The proposal
policy is deliberately deterministic and auditable; an external proposal
engine can replace it later without changing the measurement gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


PROFILES = (
    {"int_stmt": 2},
    {"int_stmt": 4},
    {"int_stmt": 8},
    {"int_stmt": 12},
    {"int_stmt": 16},
    {"scalar_to_vec": 4},
    {"scalar_to_vec": 8},
    {"vec_to_scalar": 2, "scalar_to_vec": 8},
    {"unalign_load": 4, "unalign_store": 4},
    {"unalign_load": 8, "unalign_store": 8},
)


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def existing(queue: Path) -> tuple[set[str], set[str]]:
    ids, signatures = set(), set()
    for path in queue.glob("*.json"):
        try:
            proposal = read(path)
            ids.add(str(proposal["candidate_id"]))
            signatures.add(json.dumps(proposal["changes"], sort_keys=True))
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return ids, signatures


def next_id(ids: set[str]) -> str:
    numbers = [int(value.split(".", 1)[1]) for value in ids
               if value.startswith("3.") and value.split(".", 1)[1].isdigit()]
    return f"3.{max(numbers, default=1) + 1}"


def propose(queue: Path, state: dict, memory: dict, max_pending: int) -> bool:
    ids, signatures = existing(queue)
    done = {item.get("candidate_id") for item in state.get("candidates", [])}
    pending = len(ids - done)
    if pending >= max_pending:
        return False
    handled = set(memory.get("feedback_proposals", []))
    completed = [item for item in state.get("candidates", [])
                 if item.get("status") == "complete"
                 and type(item.get("cycles")) is int and item['cycles'] > 0
                 and item.get("candidate_id") not in handled]
    if not completed:
        return False
    source = completed[-1]
    for changes in PROFILES:
        signature = json.dumps(changes, sort_keys=True)
        if signature in signatures:
            continue
        candidate_id = next_id(ids)
        proposal = {
            "candidate_id": candidate_id,
            "changes": changes,
            "rationale": (
                f"Feedback proposal derived after measured candidate "
                f"{source['candidate_id']}; explore an untested MCF-relevant cost profile."
            ),
        }
        queue.mkdir(mode=0o700, parents=True, exist_ok=True)
        (queue / f"{candidate_id}.json").write_text(json.dumps(proposal, indent=2) + "\n")
        memory.setdefault("feedback_proposals", []).append(source["candidate_id"])
        return True
    memory.setdefault("feedback_proposals", []).append(source["candidate_id"])
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True,
                        help="private proposer state; never share the controller state file")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-pending", type=int, default=4)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    while True:
        state = read(args.state)
        memory = read(args.memory) if args.memory.exists() else {"feedback_proposals": []}
        propose(args.queue, state, memory, args.max_pending)
        args.memory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.memory.write_text(json.dumps(memory, indent=2) + "\n")
        if not args.watch:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
