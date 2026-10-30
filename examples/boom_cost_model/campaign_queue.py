"""Bounded producer/consumer queue: prepare the next kernel batch during F2 work.

Run in the user's tmux. A plan contains a list of lists of compiler manifest
paths. Existing verified compiler snapshots are the queue's input; an optimizer
or a human may supply them. Completion never fabricates new work to occupy F2.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import subprocess
import sys


def command(action, config, run_dir, **options):
    cmd = [sys.executable, "-m", "examples.boom_cost_model.fast_campaign", action,
           "--config", str(config), "--run-dir", str(run_dir)]
    for key, value in options.items():
        for entry in value if isinstance(value, list) else [value]:
            cmd.extend(["--" + key, str(entry)])
    return cmd


def execute(cmd, log):
    with log.open("a") as stream:
        subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT, check=True, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--worker", help="Target one configured F2; run separate queues to partition useful batches")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if not isinstance(plan, list) or not 1 <= len(plan) <= 20 or any(
            not isinstance(batch, list) or not 1 <= len(batch) <= 16 or
            any(not isinstance(p, str) or not Path(p).is_file() for p in batch) for batch in plan):
        parser.error("plan must contain 1..20 batches of 1..16 existing compiler manifest paths")
    args.run_dir.mkdir(parents=True, exist_ok=False)
    (args.run_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    stop = False
    def request_stop(signum, frame):
        nonlocal stop
        stop = True
        print("Stop requested; draining current batch and preparation before exit.", flush=True)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def prepare(index):
        directory = args.run_dir / f"batch-{index:03d}"
        execute(command("prepare", args.config, directory, compiler=plan[index]),
                args.run_dir / f"prepare-{index:03d}.log")
        return directory

    # Child processes run in distinct sessions so Ctrl-C cannot orphan F2 work.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(prepare, 0)
        for index in range(len(plan)):
            batch = pending.result()
            if stop:
                break
            if index + 1 < len(plan):
                pending = pool.submit(prepare, index + 1)
            output = args.run_dir / f"measurement-{index:03d}"
            options = {"batch": batch}
            if args.worker:
                options["worker"] = args.worker
            execute(command("measure", args.config, output, **options),
                    args.run_dir / f"measure-{index:03d}.log")
            (args.run_dir / "progress.json").write_text(json.dumps({
                "completed_batches": index + 1, "planned_batches": len(plan),
                "last_result": str(output / "result.json"), "stop_requested": stop}, indent=2) + "\n")
            print(f"Completed hardware batch {index + 1}/{len(plan)}", flush=True)
            if stop:
                break


if __name__ == "__main__":
    main()
