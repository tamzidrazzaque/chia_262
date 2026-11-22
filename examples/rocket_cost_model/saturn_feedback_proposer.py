"""Bounded feedback proposer for the Saturn cost-model search.

This process never builds or dispatches hardware work.  It watches the private
controller state and adds at most one new proposal per completed, measured
candidate when the pending queue is below a configured bound.  The proposal
policy uses CHIA's existing Codex backend with sanitized measured history.
Only validated, previously untested cost profiles can enter the queue.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import tempfile

from examples.rocket_cost_model.vector_cost_model import BASE_COSTS, proposal as validate_proposal


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
            validate_proposal({'changes': proposal['changes'], 'rationale': 'Existing profile'})
            ids.add(str(proposal["candidate_id"]))
            signatures.add(json.dumps(proposal["changes"], sort_keys=True))
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return ids, signatures


def next_id(ids: set[str]) -> str:
    numbers = [int(value.split(".", 1)[1]) for value in ids
               if value.startswith("3.") and value.split(".", 1)[1].isdigit()]
    return f"3.{max(numbers, default=1) + 1}"


def measured_history(state: dict) -> list[dict]:
    """Allowlist numeric measured evidence; never forward logs, paths or outputs."""
    history = []
    for item in state.get('candidates', []):
        if item.get('status') != 'complete' or type(item.get('cycles')) is not int or item['cycles'] <= 0:
            continue
        changes = item.get('proposal', {}).get('changes')
        if not isinstance(changes, dict):
            continue
        validated = validate_proposal({'changes': changes, 'rationale': 'Measured history'})
        history.append({'changes': validated['changes'], 'cycles': item['cycles']})
    return history


def codex_proposal(payload: dict, model: str | None = None) -> dict:
    """Call the existing CHIA CLI backend; imports remain lazy for offline tests."""
    from chia.models.codex import CodexLLM
    with tempfile.TemporaryDirectory(prefix='saturn-proposal-') as scratch:
        llm = CodexLLM(model=model, work_dir=scratch, sandbox='read-only',
            dangerously_bypass_approvals_and_sandbox=False, approval_policy='never',
            resume_session=False, ephemeral=True, retries=1,
            system_message='Propose GCC vector costs using only the supplied numeric evidence. '
                'Do not use tools, read files, run commands, or access network services. '
                'Return only changes and rationale as JSON. Keep ISA, flags and workloads fixed.')
        result = llm.prompt(json.dumps(payload), tools=[])
        if not result.success:
            raise RuntimeError('CHIA Codex proposal failed')
        return validate_proposal(json.loads(result.result))


def propose(queue: Path, state: dict, memory: dict, max_pending: int,
            generate=codex_proposal, model: str | None = None, budget: int = 12) -> bool:
    if not 1 <= max_pending <= 16 or not 1 <= budget <= 100:
        raise ValueError('invalid proposal queue bound or total budget')
    if len(memory.get('generated', [])) >= budget:
        return False
    ids, signatures = existing(queue)
    done = {item.get("candidate_id") for item in state.get("candidates", [])}
    pending = len(ids - done)
    if pending >= max_pending:
        return False
    handled = set(memory.get("feedback_proposals", []))
    completed = [item for item in state.get("candidates", [])
                 if item.get("status") == "complete"
                 and type(item.get("cycles")) is int and item['cycles'] > 0
                 and isinstance(item.get('proposal', {}).get('changes'), dict)
                 and item.get("candidate_id") not in handled]
    if not completed:
        return False
    source = completed[-1]
    selected = validate_proposal(generate({
        'goal': 'Reduce measured MCF cycles on the fixed Saturn RVV target',
        'cost_bounds': [1, 64], 'allowed_fields': sorted(BASE_COSTS),
        'baseline_cycles': state.get('baseline', {}).get('cycles'),
        'measured_history': measured_history(state),
        'already_proposed': [json.loads(value) for value in sorted(signatures)],
        'instructions': 'Use measured outcomes to propose one untested profile. '
                        'Explain the expected code-generation effect and what would falsify it.'}, model))
    signature = json.dumps(selected['changes'], sort_keys=True)
    if signature in signatures:
        raise ValueError('model repeated an existing cost profile')
    candidate_id = next_id(ids | {value for value in done if isinstance(value, str)})
    output = {'candidate_id': candidate_id, **selected}
    queue.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Publish a complete file atomically; the consumer must never see partial JSON.
    temporary = queue / f'.{candidate_id}.pending'
    temporary.write_text(json.dumps(output, indent=2) + '\n')
    temporary.replace(queue / f'{candidate_id}.json')
    memory.setdefault("feedback_proposals", []).append(source["candidate_id"])
    memory.setdefault('generated', []).append(candidate_id)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True,
                        help="private proposer state; never share the controller state file")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-pending", type=int, default=4)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument('--model', help='Optional CHIA Codex model override')
    parser.add_argument('--budget', type=int, default=12)
    args = parser.parse_args()
    while True:
        state = read(args.state)
        memory = read(args.memory) if args.memory.exists() else {"feedback_proposals": []}
        propose(args.queue, state, memory, args.max_pending, model=args.model, budget=args.budget)
        args.memory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.memory.write_text(json.dumps(memory, indent=2) + "\n")
        if not args.watch:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
