"""Bounded, order-balanced train remeasurement of an existing focused candidate."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import threading
import traceback

import ray

from chia.chipyard.spec_validation import relative_speedup
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.focused_campaign import prepare
from examples.boom_cost_model.optimize import Experiment, save, verified_workers


def sample_plan(worker_index):
    """Use ABBA/BAAB on the workers; each position is a fresh sample key."""
    if worker_index not in (0, 1):
        raise ValueError("the paired check requires exactly two workers")
    plan = ["baseline", "candidate", "candidate", "baseline"]
    return plan if worker_index == 0 else ["candidate", "baseline", "baseline", "candidate"]


def summarize(records):
    """Keep per-worker controls and both independent timings visible."""
    result = {}
    for worker, samples in records.items():
        by_kind = {kind: [s["times"] for s in samples if s["kind"] == kind]
                   for kind in ("baseline", "candidate")}
        if any(len(v) != 2 for v in by_kind.values()):
            raise ValueError("each worker needs two samples of each compiler")
        medians = {kind: {b: statistics.median(v[b] for v in values)
                          for b in values[0]} for kind, values in by_kind.items()}
        result[worker] = {"samples": samples, "medians": medians,
                          "speedup": relative_speedup(medians["baseline"], medians["candidate"])}
    return result


def run(source, candidate_index, root):
    """Reuse validated immutable artifacts, verify workers, and drain on interrupt."""
    config = json.loads((source / "config.json").read_text())
    old = json.loads((source / "result.json").read_text())
    selected = [h for h in old["history"] if h["index"] == candidate_index and h.get("success")]
    if not old["complete"] or len(selected) != 1:
        raise ValueError("candidate must be a successful completed train observation")
    candidate = selected[0]
    specification = {"source": str(source.resolve()), "candidate_index": candidate_index,
                     "source_result_sha256": hashlib.sha256((source / "result.json").read_bytes()).hexdigest(),
                     "config": config, "plans": [sample_plan(0), sample_plan(1)],
                     "independent_samples_per_worker": 4, "inputs": "train"}
    snapshot = root / "check.json"
    if snapshot.exists() and json.loads(snapshot.read_text()) != specification:
        raise ValueError("paired-check configuration changed; use a new directory")
    save(snapshot, specification)
    if (root / "result.json").exists():
        print((root / "result.json").read_text(), flush=True)
        return
    initial = Experiment(config, root / "preflight")
    workers = verified_workers(config, initial.hardware)
    if len(workers) != 2:
        raise ValueError("the paired check requires exactly two verified workers")
    save(root / "workers.json", workers)
    # Recheck compiler, archive bytes and saved SPEC test outputs before reuse.
    baseline = prepare(config, source / "baseline-prepared")
    contender = prepare(config, source / f"candidate-{candidate_index:03d}",
                        candidate_index, candidate["proposal"])
    if contender["compiler"] != candidate["compiler"]:
        raise ValueError("candidate compiler identity changed")
    artifacts = {"baseline": baseline, "candidate": contender}
    stop, lock = threading.Event(), threading.Lock()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    state = {"active": {}, "samples": {}, "stop_requested": False}

    def update():
        state["stop_requested"] = stop.is_set()
        save(root / "progress.json", state)

    def worker_run(index, worker):
        wid = worker["instance_id"]
        ex = Experiment(config, root / f"worker-{index}")
        ex.workers = [worker]
        with lock:
            state["samples"][wid] = []
        for slot, kind in enumerate(sample_plan(index)):
            if stop.is_set():
                break
            idle = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=15", worker["ssh_alias"], "pgrep -x FireSim-f2"],
                capture_output=True, text=True, timeout=30)
            if idle.returncode != 1:
                raise RuntimeError("FPGA slot active or idle state unverifiable; preserve existing work")
            with lock:
                state["active"][wid] = f"sample {slot}: {kind}"
                update()
            timings = {}
            directory = ex.directory / f"sample-{slot:02d}-{kind}" / "train"
            # No historical cache import. Unique slot keys prevent repeat reuse.
            ex.measure_jobs(artifacts[kind]["workload"], directory / "0", "train", slot, timings)
            if set(timings) != set(config["benchmarks"]) or any(len(v) != 1 for v in timings.values()):
                raise RuntimeError("incomplete train timing set")
            record = {"slot": slot, "kind": kind, "compiler": artifacts[kind]["compiler"],
                      "times": {b: values[0] for b, values in timings.items()}, "success": True}
            save(directory / "evaluation.json", record)
            with lock:
                state["samples"][wid].append(record)
                update()
            print(f"{worker['ssh_alias']} sample {slot} {kind}: {record['times']}", flush=True)
        with lock:
            state["active"][wid] = "finished" if not stop.is_set() else "drained"
            update()

    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker_run, index, worker) for index, worker in enumerate(workers)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                errors.append(traceback.format_exc())
                stop.set()
    if errors:
        save(root / "failure.json", {"errors": errors, "inspect_drivers_before_resume": True})
        raise RuntimeError("paired check stopped after infrastructure failure; inspect saved logs/drivers")
    if stop.is_set():
        save(root / "stopped.json", {"drained": True, "resume_same_command": True})
        return
    save(root / "result.json", {"complete": True, "candidate_index": candidate_index,
         "workers": summarize(state["samples"]), "reference_checked": False,
         "interpretation": "Two train samples per compiler per worker; exploratory repeatability, not statistical proof."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=int, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / "controller.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_guard()
        save(args.run_dir / "invocation.json", {"command": sys.argv,
             "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
        try:
            run(args.source, args.candidate, args.run_dir)
        except Exception:
            save(args.run_dir / "controller-failure.json", {"traceback": traceback.format_exc()})
            raise
        finally:
            ray.shutdown()


if __name__ == "__main__":
    main()
