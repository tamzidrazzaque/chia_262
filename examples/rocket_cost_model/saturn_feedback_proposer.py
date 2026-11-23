"""Bounded feedback proposer for the Saturn cost-model search.

This process never builds or dispatches hardware work.  It watches the private
controller state and adds at most one new proposal per completed, measured
candidate when the pending queue is below a configured bound.  The proposal
policy uses CHIA's existing Codex backend with sanitized measured history.
Only validated, previously untested cost profiles can enter the queue.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import time
import tempfile
import hashlib

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
            signatures.add(profile_signature(proposal['changes']))
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return ids, signatures


def profile_signature(changes: dict) -> str:
    """Compare effective costs, including defaults omitted from sparse edits."""
    return json.dumps({**BASE_COSTS, **changes}, sort_keys=True)


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
        entry = {'changes': validated['changes'], 'cycles': item['cycles']}
        if type(item.get('baseline_cycles')) is int and item['baseline_cycles'] > 0:
            entry['baseline_cycles'] = item['baseline_cycles']
        history.append(entry)
    return history


def paired_feedback_state(root: Path, profiles: Path) -> dict:
    """Translate hash-verified fresh pairs into the proposal history schema.

    Cost edits must come from recorded proposals, never inferred from an ELF.
    The result contains numeric comparisons only, without licensed outputs.
    """
    progress = read(root / 'progress.json')
    by_bundle = {}
    for item in progress['history']:
        if item.get('status') != 'measured':
            continue
        recorded = item['proposal']
        selected = recorded if 'changes' in recorded else read(profiles / (recorded['candidate_id'] + '.json'))
        validate_proposal({key: selected[key] for key in ('changes', 'rationale')})
        by_bundle[item['candidate']['bundle_sha256']] = selected
    records = []
    samples = progress['samples']
    for offset in range(0, len(samples) - 1, 2):
        receipts = []
        for sample in samples[offset:offset + 2]:
            path = Path(sample['receipt'])
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('unsafe paired receipt path')
            receipt = read(root / path)
            checksum = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
            if checksum != sample['receipt_sha256'] or receipt.get('status') != 'correct' or receipt.get('backend') != 'fpga':
                raise ValueError('paired receipt is altered or incorrect')
            if receipt.get('whole_boot_simulation_cycles') != sample['cycles']:
                raise ValueError('paired sample cycles differ from receipt')
            receipts.append(receipt)
        roles = {r['identity']['role']: r for r in receipts}
        if set(roles) != {'2-generic-vector', '3-saturn-aware'}:
            raise ValueError('incomplete baseline/candidate pair')
        baseline, candidate = roles['2-generic-vector'], roles['3-saturn-aware']
        for field in ('worker_id', 'platform_sha256', 'input_id', 'phase'):
            if baseline['identity'].get(field) != candidate['identity'].get(field):
                raise ValueError('paired receipt controls differ')
        if candidate['identity']['phase'] == 'holdout':
            continue  # reference results never feed the proposal agent
        selected = by_bundle.get(candidate['identity']['bundle_sha256'])
        if selected is None:
            continue
        records.append({'candidate_id': selected['candidate_id'], 'status': 'complete',
            'proposal': {key: selected[key] for key in ('changes', 'rationale')},
            'cycles': candidate['whole_boot_simulation_cycles'],
            'baseline_cycles': baseline['whole_boot_simulation_cycles']})
    return {'baseline': {'cycles': records[-1]['baseline_cycles'] if records else None}, 'candidates': records}


def codex_proposal(payload: dict, model: str | None = None) -> dict:
    """Call the existing CHIA CLI backend; imports remain lazy for offline tests."""
    from chia.models.codex import CodexLLM
    settings = read(Path(__file__).with_name('saturn_proposer_model.json'))
    selected_model = model or settings['model']
    effort = settings['reasoning_effort']
    print(f'Saturn proposal model={selected_model} reasoning={effort}', flush=True)
    with tempfile.TemporaryDirectory(prefix='saturn-proposal-') as scratch:
        llm = CodexLLM(model=selected_model, reasoning_effort=effort,
            work_dir=scratch, sandbox='read-only',
            dangerously_bypass_approvals_and_sandbox=False, approval_policy='never',
            extra_cli_args=['--disable', 'shell_tool', '--disable', 'unified_exec'],
            resume_session=False, ephemeral=True, retries=1,
            system_message='Propose GCC vector costs using only the supplied numeric evidence. '
                'Do not use tools, read files, run commands, or access network services. '
                'Return only changes and rationale as JSON. Keep ISA, flags and workloads fixed.')
        result = llm.prompt(json.dumps(payload), tools=[])
        if not result.success:
            raise RuntimeError('CHIA Codex proposal failed')
        return validate_proposal(json.loads(result.result))


def publish_json(path: Path, value: dict) -> None:
    """Durably publish a JSON record while the queue-local lock is held."""
    temporary = path.with_name('.' + path.name + '.pending')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def propose(queue: Path, state: dict, memory: dict, max_pending: int,
            generate=codex_proposal, model: str | None = None, budget: int = 12) -> bool:
    """Serialize proposers and reserve each measured source before publication.

    A durable reservation consumes budget even if a crash prevents publication.
    Recovery skips that source; an operator can inspect the saved reservation
    rather than risk publishing a second proposal for the same measurement.
    """
    queue.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (queue / '.feedback.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _propose_locked(queue, state, memory, max_pending, generate, model, budget)


def _propose_locked(queue: Path, state: dict, memory: dict, max_pending: int,
                    generate, model: str | None, budget: int) -> bool:
    if not 1 <= max_pending <= 16 or not 1 <= budget <= 100:
        raise ValueError('invalid proposal queue bound or total budget')
    journal_path = queue / '.feedback-journal.state'
    journal = read(journal_path) if journal_path.exists() else {'reservations': []}
    reservations = journal['reservations']
    used_ids = set(memory.get('generated', [])) | {item['candidate_id'] for item in reservations}
    if len(used_ids) >= budget:
        return False
    ids, signatures = existing(queue)
    records = state.get('candidates', [])
    done = {item.get('candidate_id') for item in records}
    terminal = {item.get('candidate_id') for item in records
                if item.get('status') in ('complete', 'rejected')}
    active = {item.get('candidate_id') for item in records
              if item.get('status') not in ('complete', 'rejected')}
    pending = len((ids - terminal) | active)
    signatures.update(profile_signature(item['proposal']['changes']) for item in reservations)
    if pending >= max_pending:
        return False
    handled = set(memory.get("feedback_proposals", [])) | {item['source_id'] for item in reservations}
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
    signature = profile_signature(selected['changes'])
    if signature in signatures:
        raise ValueError('model repeated an existing cost profile')
    candidate_id = next_id(ids | used_ids | {value for value in done if isinstance(value, str)})
    output = {'candidate_id': candidate_id, **selected}
    reservations.append({'source_id': source['candidate_id'],
                         'receipt_sha256': source.get('receipt_sha256'),
                         'candidate_id': candidate_id, 'proposal': output})
    # This is the authoritative source/budget ledger, independent of --memory.
    # Reserve first so a crash after publishing cannot duplicate this source.
    publish_json(journal_path, journal)
    publish_json(queue / f'{candidate_id}.json', output)
    memory.setdefault("feedback_proposals", []).append(source["candidate_id"])
    memory.setdefault('generated', []).append(candidate_id)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", type=Path)
    source.add_argument('--paired-campaign', type=Path,
                        help='verified paired progress/receipt directory instead of legacy state')
    parser.add_argument('--profiles-dir', type=Path,
                        help='recorded cost proposals (defaults to queue) for paired history')
    parser.add_argument("--memory", type=Path, required=True,
                        help="private proposer state; never share the controller state file")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-pending", type=int, default=4)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument('--model', help='Optional CHIA Codex model override')
    parser.add_argument('--budget', type=int, default=12)
    args = parser.parse_args()
    while True:
        state = (paired_feedback_state(args.paired_campaign, args.profiles_dir or args.queue)
                 if args.paired_campaign else read(args.state))
        memory = read(args.memory) if args.memory.exists() else {"feedback_proposals": []}
        propose(args.queue, state, memory, args.max_pending, model=args.model, budget=args.budget)
        args.memory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.memory.write_text(json.dumps(memory, indent=2) + "\n")
        if not args.watch:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
