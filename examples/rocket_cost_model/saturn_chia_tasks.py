"""CHIA scheduling boundaries for the admitted Saturn lane.

Workers need the same private paths as the existing producer and transport.
No credentials or licensed payloads are serialized in task arguments.
Automatic task retries are disabled because F2 attempts have persistent IDs.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from chia.base.ChiaFunction import ChiaFunction, get


def invoke(module: str, candidate: str, work: str, proposal: str) -> None:
    """Run the admitted lane adapter using worker-local private configuration."""
    environment = os.environ.copy()
    environment.update(SATURN_CANDIDATE_ID=candidate, SATURN_WORKDIR=work,
                       SATURN_PROPOSAL=proposal)
    subprocess.run([sys.executable, "-m", module], env=environment, check=True)


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def prepare(candidate: str, work: str, proposal: str) -> None:
    """Build, validate and package on the configured compiler worker."""
    invoke("examples.rocket_cost_model.saturn_prepare_hook", candidate, work, proposal)


@ChiaFunction(resources={"saturn_manager": 1}, max_retries=0)
def measure(candidate: str, work: str, proposal: str) -> None:
    """Serialize access to the admitted remote Saturn manager adapter.

    saturn_manager is a singleton transport resource. The manager's existing
    physical-worker lock continues to arbitrate F2 execution across controllers.
    """
    invoke("examples.rocket_cost_model.saturn_measure_hook", candidate, work, proposal)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "measure"))
    parser.add_argument("--address", default="auto")
    args = parser.parse_args()
    import ray
    # Connect only: never silently create a second cluster/FPGA worker.
    ray.init(address=args.address)
    try:
        task = prepare if args.stage == "prepare" else measure
        get(task.chia_remote(os.environ["SATURN_CANDIDATE_ID"],
                             str(Path(os.environ["SATURN_WORKDIR"]).resolve()),
                             str(Path(os.environ["SATURN_PROPOSAL"]).resolve())))
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
