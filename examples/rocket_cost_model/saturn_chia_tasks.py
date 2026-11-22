"""CHIA scheduling boundaries for the admitted Saturn lane.

The artifact tasks move validated private bundle bytes through Ray and use
worker-local scratch. Legacy path-based tasks still require shared mounts.
Credentials remain worker-local; licensed artifact bytes require a private cluster.
Automatic task retries are disabled because F2 attempts have persistent IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from chia.base.ChiaFunction import ChiaFunction, get
from examples.rocket_cost_model.saturn_bundle_artifact import SaturnBundle, artifact_role, pack, unpack


def invoke(module: str, candidate: str, work: str, proposal: str,
           extra_environment: dict | None = None) -> None:
    """Run the admitted lane adapter using worker-local private configuration."""
    environment = os.environ.copy()
    environment.update(SATURN_CANDIDATE_ID=candidate, SATURN_WORKDIR=work,
                       SATURN_PROPOSAL=proposal)
    environment.update(extra_environment or {})
    subprocess.run([sys.executable, "-m", module], env=environment, check=True)


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def prepare(candidate: str, work: str, proposal: str) -> dict:
    """Build, validate and package on the configured compiler worker."""
    invoke("examples.rocket_cost_model.saturn_prepare_hook", candidate, work, proposal)
    return json.loads((Path(work) / 'candidate-metadata.json').read_text())


@ChiaFunction(resources={"saturn_manager": 1}, max_retries=0)
def measure(candidate: str, work: str, proposal: str) -> dict:
    """Serialize access to the admitted remote Saturn manager adapter.

    saturn_manager is a singleton transport resource. The manager's existing
    physical-worker lock continues to arbitrate F2 execution across controllers.
    """
    invoke("examples.rocket_cost_model.saturn_measure_hook", candidate, work, proposal)
    return json.loads((Path(work) / 'candidate-receipt.json').read_text())


def private_work() -> Path:
    """Allocate worker-local private scratch without requiring shared mounts."""
    root = Path(os.environ['SATURN_TASK_ROOT']).resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='saturn-task-', dir=root))


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def prepare_artifact(candidate: str, proposal: dict) -> SaturnBundle:
    """Build on compiler worker; return transferable, hash-bound bundle bytes."""
    from examples.rocket_cost_model.vector_cost_model import proposal as validate
    if not isinstance(candidate, str) or not candidate.startswith('3.') or not candidate[2:].isdigit():
        raise ValueError('invalid queue candidate ID')
    validate({key: proposal[key] for key in ('changes', 'rationale')})
    work = private_work()
    proposal_path = work / 'proposal.json'
    proposal_path.write_text(json.dumps(proposal))
    invoke('examples.rocket_cost_model.saturn_prepare_hook', candidate, str(work), str(proposal_path))
    return pack(work / 'bundle/3-saturn-aware')


def receive_artifact(artifact: SaturnBundle) -> tuple[Path, dict]:
    """Reconstruct a bundle into manager-local scratch with its bound identity."""
    work = private_work()
    role = artifact_role(artifact)
    metadata = unpack(artifact, work / 'bundle' / role)
    (work / 'candidate-metadata.json').write_text(json.dumps(metadata))
    return work, metadata


@ChiaFunction(resources={"saturn_manager": 1}, max_retries=0)
def validate_artifact(artifact: SaturnBundle) -> dict:
    """Exercise real artifact transfer/reconstruction without manager execution."""
    _, metadata = receive_artifact(artifact)
    return metadata


@ChiaFunction(resources={"saturn_manager": 1}, max_retries=0)
def measure_artifact(candidate: str, artifact: SaturnBundle, request: dict | None = None) -> dict:
    """Execute the admitted lane locally on the manager; return its receipt."""
    work, metadata = receive_artifact(artifact)
    invoke('examples.rocket_cost_model.saturn_measure_hook', candidate, str(work),
           str(work / 'unused-proposal.json'), {'SATURN_MANAGER_LOCAL': '1', 'SATURN_ROLE': metadata['role'],
               'SATURN_PHASE': (request or {}).get('phase', 'search'),
               'SATURN_SAMPLE': str((request or {}).get('sample', 0))})
    receipt = json.loads((work / 'candidate-receipt.json').read_text())
    if receipt.get('executable_sha256') != metadata['executable_sha256'] or \
            receipt.get('identity', {}).get('bundle_sha256') != metadata['bundle_sha256'] or \
            receipt.get('identity', {}).get('role') != metadata['role']:
        raise ValueError('manager receipt differs from transported artifact')
    return receipt


def select_worker(nodes: list[dict], resource: str) -> str:
    """Require advertised capacity before dispatch; manager transport is singleton."""
    eligible = [n for n in nodes if n.get('Alive') and n.get('Resources', {}).get(resource, 0) >= 1]
    if not eligible:
        raise RuntimeError(f'no live CHIA worker advertises {resource}')
    if resource == 'saturn_manager' and (len(eligible) != 1 or
            eligible[0]['Resources'][resource] != 1):
        raise RuntimeError('saturn_manager must have exactly one live worker with capacity 1')
    return eligible[0]['NodeID']


def await_task(ref, timeout: float):
    """Drain the original task after a timeout; never abandon a hardware attempt.

    The timeout is an alert threshold. Once dispatch has happened, completing
    or recovering that same task takes precedence over disconnecting the driver.
    """
    import ray
    try:
        return ray.get(ref, timeout=timeout)
    except ray.exceptions.GetTimeoutError:
        print('CHIA task exceeded its alert timeout; draining the same task before shutdown.',
              file=sys.stderr, flush=True)
        return ray.get(ref)


@ChiaFunction(num_cpus=0, max_retries=0)
def verify_worker(stage: str, marker: str, marker_sha: str, proposal: str,
                  proposal_sha: str) -> dict:
    """Check shared mounts and worker-local configuration before expensive work."""
    for path, expected in ((marker, marker_sha), (proposal, proposal_sha)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('worker private mount differs from controller')
    names = ('SATURN_SPEC_DIR', 'SATURN_BASELINE_PREFIX', 'SATURN_COMPILER_ROOT',
             'SATURN_QEMU', 'SATURN_SPECKLE', 'SATURN_TOOLCHAIN') if stage == 'prepare' else (
                 'SATURN_MANAGER_HOST', 'SATURN_MANAGER_KEY')
    for name in names:
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f'missing worker configuration: {name}')
        if name != 'SATURN_MANAGER_HOST' and not Path(value).exists():
            raise RuntimeError(f'missing worker path configured by {name}')
    return {'stage': stage, 'mounts_verified': True, 'configuration_verified': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "measure"))
    parser.add_argument("--address", default="auto")
    parser.add_argument('--preflight-timeout', type=float, default=30)
    parser.add_argument('--task-timeout', type=float, default=28800)
    args = parser.parse_args()
    import ray
    # Connect only: never silently create a second cluster/FPGA worker.
    ray.init(address=args.address)
    try:
        from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
        resource = 'riscv_build' if args.stage == 'prepare' else 'saturn_manager'
        worker = select_worker(ray.nodes(), resource)
        affinity = NodeAffinitySchedulingStrategy(worker, soft=False)
        work = Path(os.environ['SATURN_WORKDIR']).resolve()
        proposal = Path(os.environ['SATURN_PROPOSAL']).resolve()
        with tempfile.NamedTemporaryFile(dir=work, prefix='.chia-mount-', delete=True) as marker:
            marker.write(os.urandom(32))
            marker.flush()
            ref = verify_worker.options(scheduling_strategy=affinity).chia_remote(
                args.stage, marker.name, hashlib.sha256(Path(marker.name).read_bytes()).hexdigest(),
                str(proposal), hashlib.sha256(proposal.read_bytes()).hexdigest())
            ray.get(ref, timeout=args.preflight_timeout)
        task = prepare if args.stage == "prepare" else measure
        ref = task.options(scheduling_strategy=affinity).chia_remote(
            os.environ['SATURN_CANDIDATE_ID'], str(work), str(proposal))
        result = await_task(ref, args.task_timeout)
        print(json.dumps(result, sort_keys=True))
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
