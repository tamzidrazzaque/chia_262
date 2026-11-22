"""Fail-closed controller for the Saturn-aware role-3 search loop.

The controller deliberately delegates candidate preparation and F2 execution to
hooks.  CHIA and the protected manager lane own those operations; this process
only sequences them, validates their receipts, and records decisions.  Private
SPEC files, binaries, credentials, and raw logs never enter the state file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time


def _read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_hook(command: str, env: dict[str, str], label: str) -> None:
    rendered = command.format(
        candidate_id=env["SATURN_CANDIDATE_ID"],
        proposal=shlex.quote(env["SATURN_PROPOSAL"]),
        workdir=shlex.quote(env["SATURN_WORKDIR"]),
    )
    result = subprocess.run(rendered, shell=True, env=env, text=True)
    if result.returncode:
        raise RuntimeError(f"{label} hook failed with exit {result.returncode}")


def _validate_receipt(receipt: dict, baseline: dict, candidate_id: str) -> dict:
    if receipt.get("status") != "correct":
        raise ValueError("candidate receipt is not marked correct")
    identity = receipt.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("candidate receipt lacks identity")
    if identity.get("role") != "3-saturn-aware":
        raise ValueError("candidate receipt is not role 3")
    if identity.get("candidate_id") not in (None, candidate_id):
        raise ValueError("candidate identity does not match queue entry")
    for key in ("platform_sha256", "agfi", "driver_sha256", "vlen_bits", "input_id"):
        if identity.get(key) != baseline.get(key):
            raise ValueError(f"candidate platform/input mismatch: {key}")
    cycles = receipt.get("whole_boot_simulation_cycles")
    if type(cycles) is not int or cycles <= 0:
        raise ValueError("candidate receipt lacks positive cycle count")
    return {"cycles": cycles, "guest_seconds": receipt.get("target_guest_elapsed_seconds"),
            "bundle_sha256": identity.get("bundle_sha256"),
            "executable_sha256": receipt.get("collected_sha256", {}).get("result/executable.sha256")}


def _decision(candidate: dict, baseline: dict) -> dict:
    delta = baseline["cycles"] - candidate["cycles"]
    return {"candidate_cycles": candidate["cycles"], "baseline_cycles": baseline["cycles"],
            "cycle_delta": delta, "relative_improvement": delta / baseline["cycles"],
            "accepted_provisionally": delta > 0}


def run(args: argparse.Namespace) -> None:
    queue = Path(args.queue).resolve()
    state_path = Path(args.state).resolve()
    work_root = Path(args.work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    baseline = _read(Path(args.baseline))
    required = ("platform_sha256", "agfi", "driver_sha256", "vlen_bits", "input_id", "cycles")
    if any(key not in baseline for key in required) or type(baseline["cycles"]) is not int:
        raise ValueError("baseline must contain frozen platform identity and cycles")
    state = _read(state_path) if state_path.exists() else {
        "schema_version": 1, "baseline": baseline, "candidates": []}
    if state.get("baseline") != baseline:
        raise ValueError("baseline changed after loop initialization")
    done = {item["candidate_id"] for item in state.get("candidates", [])}
    seen_elves = {item.get("executable_sha256") for item in state.get("candidates", [])
                  if item.get("executable_sha256")}
    if baseline.get("executable_sha256"):
        seen_elves.add(baseline["executable_sha256"])
    while True:
      proposals = sorted(
          queue.glob("*.json"),
          key=lambda path: (int(path.stem.split(".", 1)[1])
                            if path.stem.startswith("3.") and path.stem.split(".", 1)[1].isdigit()
                            else 10**9, path.name),
      )
      progressed = False
      for proposal_path in proposals:
          proposal = _read(proposal_path)
          candidate_id = proposal.get("candidate_id")
          if not isinstance(candidate_id, str) or not candidate_id.startswith("3."):
              raise ValueError(f"invalid candidate_id in {proposal_path}")
          if candidate_id in done:
              continue
          candidate_work = work_root / candidate_id
          candidate_work.mkdir(mode=0o700)
          record = {"candidate_id": candidate_id, "proposal_sha256": _digest(proposal_path),
                    "started_at": time.time(), "status": "preparing"}
          (candidate_work / "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n")
          env = os.environ.copy()
          env.update({"SATURN_CANDIDATE_ID": candidate_id,
                      "SATURN_PROPOSAL": str(proposal_path),
                      "SATURN_WORKDIR": str(candidate_work)})
          try:
              _run_hook(args.prepare_cmd, env, "prepare")
              metadata_path = candidate_work / "candidate-metadata.json"
              if metadata_path.exists():
                  metadata = _read(metadata_path)
                  executable = metadata.get("executable_sha256")
                  if not isinstance(executable, str) or len(executable) != 64:
                      raise ValueError("candidate metadata lacks executable_sha256")
                  if executable in seen_elves:
                      record.update(status="rejected", failure="duplicate executable",
                                    executable_sha256=executable, finished_at=time.time())
                      state["candidates"].append(record)
                      state_path.parent.mkdir(parents=True, exist_ok=True)
                      state_path.write_text(json.dumps(state, indent=2) + "\n")
                      done.add(candidate_id)
                      progressed = True
                      if args.once:
                          return
                      continue
                  record["executable_sha256"] = executable
              record["status"] = "measuring"
              _run_hook(args.measure_cmd, env, "measure")
              receipt = _read(candidate_work / "candidate-receipt.json")
              candidate = _validate_receipt(receipt, baseline, candidate_id)
              record.update(candidate, decision=_decision(candidate, baseline), status="complete")
              seen_elves.add(candidate["executable_sha256"])
          except Exception as exc:  # record the failure and stop; never skip evidence
              record.update(status="rejected", failure=str(exc))
              state["candidates"].append(record)
              state_path.parent.mkdir(parents=True, exist_ok=True)
              state_path.write_text(json.dumps(state, indent=2) + "\n")
              raise
          record["finished_at"] = time.time()
          state["candidates"].append(record)
          state_path.parent.mkdir(parents=True, exist_ok=True)
          state_path.write_text(json.dumps(state, indent=2) + "\n")
          done.add(candidate_id)
          progressed = True
          if args.once:
              return
      if not args.watch:
          return
      if not progressed:
          time.sleep(args.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True, help="private directory of candidate proposal JSON files")
    parser.add_argument("--baseline", required=True, help="private frozen role-2 baseline receipt")
    parser.add_argument("--state", required=True, help="private loop state JSON")
    parser.add_argument("--work-root", required=True, help="private per-candidate work directory")
    parser.add_argument("--prepare-cmd", required=True, help="hook that builds/stages a candidate")
    parser.add_argument("--measure-cmd", required=True, help="hook that runs F2 and writes candidate-receipt.json")
    parser.add_argument("--once", action="store_true", help="process one candidate and exit")
    parser.add_argument("--watch", action="store_true", help="keep polling for newly queued proposals")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
