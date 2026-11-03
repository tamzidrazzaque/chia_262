"""A bounded, adaptive BOOM campaign using real SPEC train feedback on two F2s.

One producer builds/QEMU-validates application images ahead of two fixed physical
workers. Four coordinated BOOM profiles seed the run; later proposals use the
authenticated Claude CLI and measured train feedback. Reference inputs stay
outside proposal generation. Start the long controller in the user's tmux.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import traceback
import sys
import time

import ray

from chia.base.ChiaFunction import get
from chia.chipyard.cost_model import BASELINE_GCC_SHA256
from chia.chipyard.measurements import prior_train_evidence
from chia.chipyard.spec_validation import relative_speedup
from chia.chipyard.state_def import FireMarshalArtifact
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model import campaign_proposals
from examples.boom_cost_model.optimize import Experiment, CandidateRejected, save, verified_workers
from examples.boom_cost_model.tasks import compiler_stage, workload_fingerprints

REFINEMENT_KINDS = ("pressure-refine", "cost-refine", "adaptive-refine")
GUIDED_KINDS = ("pressure", "adaptive", *REFINEMENT_KINDS)

class CampaignStopped(Exception):
    """The current measurement was saved and a stop prevents further dispatch."""


def proposal_api(config):
    if config.get("campaign_kind") in REFINEMENT_KINDS:
        for field in ("incumbent_run", "incumbent_result_sha256", "incumbent_compiler_id"):
            if not isinstance(config.get(field), str) or not config[field]:
                raise ValueError("refinement requires " + field)
    if config.get("campaign_kind") in ("adaptive", "adaptive-refine"):
        from examples.boom_cost_model.adaptive_proposals import AdaptiveProposals
        return AdaptiveProposals(config)
    if config.get("campaign_kind") == "cost-refine":
        from examples.boom_cost_model.cost_refinement_proposals import CostRefinementProposals
        return CostRefinementProposals(config)
    if config.get("campaign_kind") == "pressure-refine":
        from examples.boom_cost_model import refinement_proposals
        return refinement_proposals
    if config.get("campaign_kind", "coordinated") == "pressure":
        from examples.boom_cost_model import pressure_proposals
        return pressure_proposals
    return campaign_proposals


def code_identity(fingerprints):
    """Compare all benchmark executable bytes, excluding build paths/names."""
    result = {}
    for name, record in fingerprints.items():
        benchmark = name.rsplit("-", 1)[-1]
        binaries = record.get("executables", {})
        if not binaries:
            raise ValueError("missing application executable fingerprints")
        result[benchmark] = dict(binaries)
    return result


def validate_config(config):
    if config.get("campaign_kind", "coordinated") not in ("coordinated", *GUIDED_KINDS):
        raise ValueError("unknown campaign_kind")
    if config.get("campaign_kind") in REFINEMENT_KINDS:
        margin = config.get("min_incremental_improvement", 0.005)
        if type(margin) not in (int, float) or not 0 < margin <= 0.1:
            raise ValueError("invalid incremental improvement margin")
        if type(config.get("confirmation_worker_index")) is not int or config["confirmation_worker_index"] not in (0, 1):
            raise ValueError("refinement requires confirmation_worker_index 0 or 1")
    budget = config.get("campaign_budget", 6)
    if type(budget) is not int or not 2 <= budget <= 12:
        raise ValueError("campaign budget must be 2..12")
    reserved = config.get("reserved_profile_ids", [])
    if not isinstance(reserved, list) or any(not isinstance(k, str) or len(k) != 64 or
            any(c not in '0123456789abcdef' for c in k) for k in reserved):
        raise ValueError("invalid reserved profile identities")
    adaptive = config.get("campaign_kind") in ("adaptive", "adaptive-refine")
    feedback = config.get('feedback_min_completed')
    if feedback is not None and (not adaptive or type(feedback) is not int or not 2 <= feedback <= 8):
        raise ValueError('early feedback requires an adaptive campaign and 2..8 completed profiles')
    if adaptive and config["benchmarks"] not in (["648.exchange2_s"], ["641.leela_s"], ["602.gcc_s"]):
        raise ValueError("adaptive targets require one explicitly approved benchmark")
    if not adaptive and config["benchmarks"] != ["648.exchange2_s"]:
        raise ValueError("this first focused campaign explicitly targets Exchange2; expand only in a new experiment")
    count = config.get("confirm_repeats", 3)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("confirmation repeats must be 1..5")
    if type(config.get('prepare_seed_count',2)) is not int or not 1 <= config.get('prepare_seed_count',2) <= 8:
        raise ValueError('prepare_seed_count must be 1..8')
    if not 0 <= config["min_improvement"] <= 0.1:
        raise ValueError("invalid selection threshold")
    for field, default in (("train_timeout_seconds", 5400), ("ref_timeout_seconds", 259200)):
        value = config.get(field, default)
        if type(value) is not int or not 60 <= value <= 604800:
            raise ValueError("invalid hardware timeout")
    return budget


def import_baseline_cache(directory, sources, allowed_labels=("baseline-f2", "baseline-heldout")):
    """Import selected metadata; exact-key/raw-output/native checks gate reuse."""
    directory.mkdir(parents=True, exist_ok=True)
    for source in sources:
        for path in Path(source).glob("*.json"):
            record = json.loads(path.read_text())
            # Ref entries are available only to final confirmation, never to
            # the producer/prompt. Actual reuse revalidates bytes and native output.
            if not any(label in Path(record["source"]).parts for label in allowed_labels):
                continue
            if path.stem != record["key"] or len(path.stem) != 64 or any(c not in "0123456789abcdef" for c in path.stem):
                raise ValueError("invalid baseline cache key")
            dest = directory / path.name
            if not dest.exists():
                shutil.copyfile(path, dest)


def verify_incumbent_archive(config, hardware):
    """Pin a completed, train-confirmed incumbent on this exact hardware."""
    source = Path(config["incumbent_run"])
    path = source / "result.json"
    if hashlib.sha256(path.read_bytes()).hexdigest() != config["incumbent_result_sha256"]:
        raise ValueError("incumbent archive result changed")
    result = json.loads(path.read_text())
    if result.get("benchmarks", config["benchmarks"]) != config["benchmarks"]:
        raise ValueError("incumbent benchmark differs")
    if not result.get("complete") or not result.get("train_confirmation_checked"):
        raise ValueError("incumbent must have completed train confirmation")
    score = result.get("confirmed_train_speedup")
    if result.get("confirmation_failed") or result.get("baseline_retained") or type(score) not in (int, float) or not math.isfinite(score) or score <= 1:
        raise ValueError("incumbent must have passed train confirmation")
    best = result["best_train_proposal"]
    if not best.get("success") or best["compiler"]["compiler_id"] != config["incumbent_compiler_id"]:
        raise ValueError("incumbent compiler identity differs")
    api = proposal_api(config)
    if api.identity(best["proposal"]) != api.identity(api.seed_profiles()[0]):
        raise ValueError("refinement control differs from verified incumbent")
    previous = json.loads((source / f"worker-{best['worker_index']}" / "hardware.json").read_text())
    if previous != hardware:
        raise ValueError("incumbent hardware manifest differs")
    archives = [{"source": str(source), "index": best["index"]}]
    histories = list(result["history"])
    supporting = config.get("incumbent_supporting_runs", [])
    if not isinstance(supporting, list) or len(supporting) > 4:
        raise ValueError("invalid supporting archive list")
    for item in supporting:
        directory = Path(item["run_dir"])
        path = directory / "result.json"
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["result_sha256"]:
            raise ValueError("supporting archive result changed")
        report = json.loads(path.read_text())
        if report.get("benchmarks", config["benchmarks"]) != config["benchmarks"]:
            raise ValueError("supporting archive benchmark differs")
        selected = report.get("selected_train_proposal", report.get("best_train_proposal"))
        if not report.get("complete") or not selected or not selected.get("success"):
            raise ValueError("supporting archive lacks a completed selected control")
        if selected["compiler"]["compiler_id"] != best["compiler"]["compiler_id"] or api.identity(selected["proposal"]) != api.identity(best["proposal"]):
            raise ValueError("supporting archive selected another compiler")
        if json.loads((directory / f"worker-{selected['worker_index']}" / "hardware.json").read_text()) != hardware:
            raise ValueError("supporting archive hardware differs")
        archives.append({"source": str(directory), "index": selected["index"]})
        histories.extend(report["history"])
    return {"source": str(source), "index": best["index"], "compiler_id": best["compiler"]["compiler_id"],
            "previous_history": histories, "cache_archives": archives,
            "result_sha256": config["incumbent_result_sha256"]}


def prepare(config, directory, index=None, proposal=None):
    directory.mkdir(parents=True, exist_ok=True)
    ex = Experiment(config, directory)
    if proposal is None:
        actual = get(compiler_stage.options(**ex.affinity).chia_remote(config["gcc_root"], config["baseline_prefix"]))
        if actual["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256:
            raise ValueError("original compiler changed")
        selected = {"compiler_id": BASELINE_GCC_SHA256, "prefix": config["baseline_prefix"]}
    else:
        proposal_api(config).validate(proposal)
        actual = get(compiler_stage.options(**ex.affinity).chia_remote(config["gcc_root"], config["baseline_prefix"],
            proposal["costs"], None, "boom", proposal["move_profile"], proposal.get("policy")))
        selected = {"compiler_id": actual["compiler_id"], "prefix": actual["prefix"]}
        if config.get("campaign_kind") in REFINEMENT_KINDS and index == 0 and selected["compiler_id"] != config["incumbent_compiler_id"]:
            raise ValueError("rebuilt refinement control differs from incumbent snapshot")
        save(directory / "proposal.json", proposal)
    save(directory / "compiler.json", actual)
    prepared = directory / "prepared.json"
    train = directory / "train"
    if prepared.exists():
        record = json.loads(prepared.read_text())
        archive = (train / "workload.tar.gz").read_bytes()
        if record["compiler"] != selected or record["archive_sha256"] != hashlib.sha256(archive).hexdigest():
            raise ValueError("prepared compiler/image changed")
        # Recheck saved test outputs with the native harness on every resume.
        test_jobs = list((directory / "qemu/test/0").glob("*/collected"))
        if len(test_jobs) != len(config["benchmarks"]):
            raise ValueError("prepared QEMU output set is incomplete")
        for output in test_jobs:
            files = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            ex.collect(files, output.parent, "test", True)
        workload = FireMarshalArtifact(archive=archive, json_name=record["descriptor"])
    else:
        ex.evaluate(selected, "test", "qemu", qemu=True)
        workload = ex.workload(selected, "train", train)
    fingerprints = get(workload_fingerprints.chia_remote(workload.json_name))
    codes = code_identity(fingerprints)
    record = {"index": index, "compiler": selected, "descriptor": workload.json_name,
              "archive_sha256": hashlib.sha256(workload.archive).hexdigest(), "code_generation": codes}
    save(prepared, record)
    return {**record, "workload": workload, "proposal": proposal}


def measure(ex, prepared, label, inputs="train", repeats=1, stop=None):
    timings = {}
    for repeat in range(repeats):
        if stop is not None and stop.is_set():
            raise CampaignStopped()
        worker = ex.workers[0]
        active = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=15", worker["ssh_alias"], "pgrep -x FireSim-f2"],
            capture_output=True, text=True, timeout=30)
        if active.returncode != 1:
            raise RuntimeError("FPGA driver active or idle state unverifiable; preserve existing work")
        ex.measure_jobs(prepared["workload"], ex.directory / label / inputs / str(repeat), inputs, repeat, timings)
    if set(timings) != set(ex.config["benchmarks"]) or any(len(v) != repeats for v in timings.values()):
        raise RuntimeError("incomplete hardware timing set")
    import statistics
    result = {"success": True, "compiler": prepared["compiler"], "inputs": inputs,
              "FPGA_executed": True, "raw_times": timings,
              "times": {k: statistics.median(v) for k, v in timings.items()}}
    save(ex.directory / label / inputs / "evaluation.json", result)
    return result


def run(config, root, prepare_only=False):
    budget = validate_config(config)
    api = proposal_api(config)
    seeds = api.seed_profiles()
    adaptive = config.get('campaign_kind') in ('adaptive','adaptive-refine')
    required_feedback = config.get('feedback_min_completed',min(2,len(seeds)) if adaptive else len(seeds) if config.get('campaign_kind') in GUIDED_KINDS else 1)
    if required_feedback > len(seeds):
        raise ValueError('feedback minimum exceeds seed count')
    save(root / 'scheduling.json',{'seed_count':len(seeds),'feedback_min_completed':required_feedback,
        'control_result_required':adaptive,'pending_profiles_have_no_scores':True})
    if prepare_only:
        preparing_stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: preparing_stop.set())
        signal.signal(signal.SIGTERM, lambda *_: preparing_stop.set())
        baseline = prepare(config, root / "baseline-prepared")
        if preparing_stop.is_set():
            raise CampaignStopped()
        reports = []
        for index in range(min(config.get('prepare_seed_count',2), len(seeds), budget)):
            item = prepare(config, root / f"candidate-{index:03d}", index, seeds[index])
            if preparing_stop.is_set():
                raise CampaignStopped()
            reports.append({"index": index, "compiler": item["compiler"],
                            "codegen_identical_to_baseline": item["code_generation"] == baseline["code_generation"]})
        save(root / "readiness.json", {"prepared_only": True, "FPGA_executed": False, "candidates": reports})
        return

    check = Experiment(config, root / "preflight")
    anchor = verify_incumbent_archive(config, check.hardware) if config.get("campaign_kind") in REFINEMENT_KINDS else None
    if anchor:
        save(root / "incumbent-archive.json", anchor)
    workers = verified_workers(config, check.hardware)
    if len(workers) != 2:
        raise ValueError("this campaign requires the two configured independent F2 workers")
    save(root / "workers.json", workers)
    prior = prior_train_evidence(config.get("prior_runs", []), check.hardware)
    save(root / "prior-train-evidence.json", prior)
    stop, baseline_ready = threading.Event(), threading.Event()
    condition = threading.Condition()
    queues = [queue.Queue(maxsize=2) for _ in workers]
    state = {"history": [], "baselines": {}, "reserved": list(config.get("reserved_profile_ids", [])), "prepared": [], "active": {}}
    if anchor:
        incumbent_key = api.identity(seeds[0])
        for h in anchor["previous_history"]:
            if not h.get("success"):
                continue
            try:
                key = api.identity(h["proposal"])
            except (ValueError, TypeError):
                continue  # A prior observation outside this search domain is context only.
            if key != incumbent_key and key not in state["reserved"]:
                state["reserved"].append(key)
    baseline_holder = {}
    pending_proposals = {}

    def progress():
        save(root / "progress.json", {**state, "stop_requested": stop.is_set(), "budget": budget})

    def request_stop(signum, frame):
        stop.set()
        print("Stop requested; active compiler/FPGA work will drain and be saved.", flush=True)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def producer():
        try:
            baseline = prepare(config, root / "baseline-prepared")
            baseline_holder.update(baseline)
            baseline_ready.set()
            for index in range(budget):
                if stop.is_set():
                    break
                dest = root / f"candidate-{index:03d}"
                path = dest / "proposal.json"
                if path.exists():
                    suggestion = api.validate(json.loads(path.read_text()))
                elif index < len(seeds):
                    suggestion = seeds[index]
                else:
                    with condition:
                        feedback_timeout = config.get("train_timeout_seconds", 5400) * (len(seeds) + 1)
                        ready = condition.wait_for(lambda: stop.is_set() or (
                            len(state['history']) >= required_feedback and (
                                not adaptive or any(h['index'] == 0 for h in state['history']))), timeout=feedback_timeout)
                        if stop.is_set():
                            break
                        if not ready:
                            raise RuntimeError("timed out waiting for completed seed feedback")
                        history = list(state["history"])
                        if config.get("campaign_kind") in GUIDED_KINDS:
                            completed = {h["index"] for h in history}
                            history += [{"index": i, "proposal": p, "pending": True}
                                        for i, p in pending_proposals.items() if i not in completed]
                    try:
                        suggestion = api.feedback_proposal(config, history, prior, root / "claude" / f"proposal-{index:03d}")
                    except (ValueError, TypeError) as exc:
                        record = {"index": index, "success": False, "failure": "invalid proposal: " + str(exc)}
                        save(root / f"candidate-{index:03d}.json", record)
                        with condition:
                            state["history"].append(record)
                            condition.notify_all()
                            progress()
                        continue
                key = api.identity(suggestion)
                with condition:
                    if key in state["reserved"]:
                        record = {"index": index, "proposal": suggestion, "success": False,
                                  "failure": "proposal repeats a reserved or tested coordinated profile"}
                        state["history"].append(record)
                        save(root / f"candidate-{index:03d}.json", record)
                        condition.notify_all()
                        progress()
                        continue
                    state["reserved"].append(key)
                    pending_proposals[index] = suggestion
                    progress()
                try:
                    item = prepare(config, dest, index, suggestion)
                    same = item["code_generation"] == baseline["code_generation"]
                    with condition:
                        # Equal application bytes provide no new code-generation
                        # evidence. Mark skipped without inventing a timing score.
                        seen = [x["code_generation"] for x in state["prepared"]]
                        duplicate = same or item["code_generation"] in seen
                        state["prepared"].append({"index": index, "code_generation": item["code_generation"]})
                        if duplicate:
                            record = {"index": index, "proposal": suggestion, "success": False,
                                "skipped": "application executable bytes duplicate baseline/another prepared candidate"}
                            state["history"].append(record)
                            save(root / f"candidate-{index:03d}.json", record)
                            condition.notify_all()
                        progress()
                    if duplicate:
                        continue
                    while not stop.is_set():
                        try:
                            queues[index % len(workers)].put(item, timeout=1)
                            break
                        except queue.Full:
                            pass
                except CandidateRejected as exc:
                    record = {"index": index, "proposal": suggestion, "success": False, "failure": str(exc)}
                    save(root / f"candidate-{index:03d}.json", record)
                    save(dest / "preparation-failure.json", {"traceback": traceback.format_exc()})
                    with condition:
                        state["history"].append(record)
                        progress()
                        condition.notify_all()
        except Exception:
            save(root / "producer-failure.json", {"traceback": traceback.format_exc()})
            stop.set()
            baseline_ready.set()
            raise
        finally:
            baseline_holder["producer_finished"] = True

    def consumer(worker_index):
        try:
            while not baseline_ready.wait(1):
                if stop.is_set():
                    return
            if stop.is_set():
                return
            worker = workers[worker_index]
            directory = root / f"worker-{worker_index}"
            ex = Experiment(config, directory)
            ex.workers = [worker]
            import_baseline_cache(directory / "measurement-cache", config.get("baseline_cache_dirs", []))
            if anchor:
                for archived in anchor["cache_archives"]:
                    cache_dirs = [str(p) for p in Path(archived["source"]).glob("worker-*/measurement-cache")]
                    labels = ("baseline-f2", "confirm-baseline", "confirm-winner", f"candidate-{archived['index']:03d}-f2")
                    import_baseline_cache(directory / "measurement-cache", cache_dirs, labels)
            with condition:
                state["active"][worker["instance_id"]] = "baseline train / validated cache"
                progress()
            baseline = measure(ex, baseline_holder, "baseline-f2")
            with condition:
                state["baselines"][worker["instance_id"]] = baseline["times"]
                state["active"][worker["instance_id"]] = "waiting for prepared candidate"
                progress()
            while not stop.is_set():
                try:
                    item = queues[worker_index].get(timeout=1)
                except queue.Empty:
                    if baseline_holder.get("producer_finished"):
                        with condition:
                            state["active"][worker["instance_id"]] = "finished"
                            progress()
                        return
                    continue
                index = item["index"]
                record = {"index": index, "proposal": item["proposal"], "compiler": item["compiler"],
                          "instance_id": worker["instance_id"], "worker_index": worker_index}
                with condition:
                    state["active"][worker["instance_id"]] = f"candidate {index} train"
                    progress()
                try:
                    value = measure(ex, item, f"candidate-{index:03d}-f2")
                    record.update(success=True, train_times=value["times"],
                                  speedup=relative_speedup(baseline["times"], value["times"]))
                except CandidateRejected as exc:
                    record.update(success=False, failure=str(exc))
                save(root / f"candidate-{index:03d}.json", record)
                with condition:
                    state["history"].append(record)
                    state["active"][worker["instance_id"]] = "waiting for prepared candidate"
                    progress()
                    condition.notify_all()
                print(f"Candidate {index}: {record.get('speedup', record.get('failure'))}", flush=True)
        except Exception:
            save(root / f"worker-{worker_index}-failure.json", {"traceback": traceback.format_exc()})
            stop.set()
            with condition:
                condition.notify_all()
            raise

    errors = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(producer), *(pool.submit(consumer, i) for i in range(len(workers)))]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors.append(str(exc))
                stop.set()
    if errors:
        raise RuntimeError("campaign tasks saved after infrastructure failure; inspect drivers before resuming: " + "; ".join(errors))
    if stop.is_set():
        save(root / "stopped.json", {"drained": True, "resume_same_command": True})
        return
    successful = [h for h in state["history"] if h.get("success")]
    best = max(successful, key=lambda h: h["speedup"], default=None)
    result = {"complete": True, "benchmarks": config["benchmarks"], "history": state["history"],
              "baseline_retained": best is None or best["speedup"] < 1 + config["min_improvement"],
              "best_train_proposal": best, "reference_checked": False, "SPEC_reportable_score": False}
    incumbent = None
    if anchor:
        incumbent = next((h for h in successful if h["index"] == 0), None)
        if incumbent is None:
            raise RuntimeError("no validated incumbent control; cannot select a refinement")
        incremental = relative_speedup(incumbent["train_times"], best["train_times"])
        promoted = not result["baseline_retained"] and best["index"] != 0 and incremental >= 1 + config.get("min_incremental_improvement", 0.005)
        result.update(incumbent_control=incumbent, best_incremental_speedup=incremental,
                      incumbent_retained=not promoted, selected_train_proposal=best if promoted else incumbent)
        if not promoted:
            save(root / "result.json", result)
            print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2), flush=True)
            return
    confirm = config.get("campaign_kind") in GUIDED_KINDS or config.get("final_ref", True)
    if best and not result["baseline_retained"] and confirm:
        wi = config.get("confirmation_worker_index", best["worker_index"]) if anchor else best["worker_index"]
        ex = Experiment(config, root / f"worker-{wi}")
        ex.workers = [workers[wi]]
        candidate = prepare(config, root / f"candidate-{best['index']:03d}", best["index"], best["proposal"])
        count = config.get("confirm_repeats", 3)
        base = measure(ex, baseline_holder, "confirm-baseline", repeats=count, stop=stop)
        incumbent_time = None
        if incumbent is not None:
            old = prepare(config, root / "candidate-000", 0, incumbent["proposal"])
            incumbent_time = measure(ex, old, "confirm-incumbent", repeats=count, stop=stop)
        winner = measure(ex, candidate, "confirm-winner", repeats=count, stop=stop)
        result["confirmed_train_speedup"] = relative_speedup(base["times"], winner["times"])
        result["train_confirmation_checked"] = True
        if incumbent_time:
            result["confirmed_incremental_speedup"] = relative_speedup(incumbent_time["times"], winner["times"])
            result["confirmation_worker_index"] = wi
            if result["confirmed_incremental_speedup"] < 1 + config.get("min_incremental_improvement", 0.005):
                result.update(incumbent_retained=True, confirmation_failed=True, selected_train_proposal=incumbent)
                save(root / "result.json", result)
                return
        if result["confirmed_train_speedup"] < 1 + config["min_improvement"]:
            result.update(baseline_retained=True, confirmation_failed=True)
            if incumbent is not None:
                result.update(incumbent_retained=True, selected_train_proposal=incumbent)
            save(root / "result.json", result)
            return
        if not config.get("final_ref", True):
            save(root / "result.json", result)
            print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2), flush=True)
            return
        for name, selected in (("baseline-heldout", baseline_holder), ("winner-heldout", candidate)):
            artifact = ex.workload(selected["compiler"], "ref", root / name / "build")
            measured = measure(ex, {**selected, "workload": artifact}, name, inputs="ref", stop=stop)
            result[name] = measured["times"]
        result.update(reference_checked=True, reference_speedup=relative_speedup(
            result["baseline-heldout"], result["winner-heldout"]))
    save(root / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / "controller.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads(args.config.read_text())
        snapshot = args.run_dir / "config.json"
        if snapshot.exists() and json.loads(snapshot.read_text()) != config:
            raise ValueError("campaign config changed; use a new run directory")
        save(snapshot, config)
        invocation_sources = [Path(__file__), Path(__file__).with_name("campaign_proposals.py"),
            Path(__file__).with_name("pressure_proposals.py"),
            Path(__file__).with_name("refinement_proposals.py"),
            Path(__file__).with_name("cost_refinement_proposals.py"),
            Path(__file__).with_name("adaptive_proposals.py"),
            Path(__file__).parents[2] / "chia/chipyard/boom_model.py",
            Path(__file__).parents[2] / "chia/chipyard/cost_model.py",
            Path(__file__).with_name("tasks.py"), Path(__file__).with_name("optimize.py")]
        save(args.run_dir / "invocations" / f"{time.time_ns()}.json", {
            "command": sys.argv, "prepare_only": args.prepare_only,
            "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in invocation_sources}})
        require_guard()
        ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
        try:
            run(config, args.run_dir, args.prepare_only)
        except CampaignStopped:
            save(args.run_dir / "stopped.json", {"drained": True, "resume_same_command": True})
        except Exception:
            save(args.run_dir / "failure.json", {"traceback": traceback.format_exc()})
            raise
        finally:
            ray.shutdown()


if __name__ == "__main__":
    main()
