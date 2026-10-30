"""Next-iteration scheduling, parallelism and sample provenance checks."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from chia.chipyard.cost_model import BASE_COSTS, render_scheduling, validate_scheduling
from chia.chipyard.measurements import measurement_key, tree_identity, validated_cache, prior_train_evidence
from chia.chipyard.spec_validation import real_time
from chia.firesim.state_def import SimJobResult
from examples.boom_cost_model import optimize


@pytest.mark.parametrize("value", [0, 9, True, "3", 2.5])
def test_issue_rate_bounds(value):
    with pytest.raises(ValueError):
        validate_scheduling({"issue_rate": value})


def test_issue_rate_is_a_separate_experiment():
    text = "static const struct riscv_tune_param rocket_tune_info = {\n  1, /* issue_rate */\n};"
    assert "3, /* issue_rate */" in render_scheduling(text, {"issue_rate": 3})
    with pytest.raises(ValueError):
        validate_scheduling({"issue_rate": 3, "slow_unaligned_access": False})
    proposed = {"costs": BASE_COSTS, "scheduling": {"issue_rate": 3}, "rationale": "isolate issue rate"}
    assert optimize.proposal(json.dumps(proposed), True) == proposed
    with pytest.raises(ValueError):
        optimize.proposal(json.dumps(proposed))
    proposed["costs"] = {**BASE_COSTS, "branch_cost": 4}
    with pytest.raises(ValueError, match="hold optimization costs fixed"):
        optimize.proposal(json.dumps(proposed), True)


def test_probe_harness_native_correctness(tmp_path):
    from examples.boom_cost_model.prepare_probes import probe_checksums, validate_probes
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("native C compiler unavailable")
    source = Path(optimize.__file__).with_name("latency_probe.c")
    binary = tmp_path / "probe"
    subprocess.run([cc, "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-O3", str(source), "-o", str(binary)],
                   check=True, capture_output=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 6
    assert all(r["correct"] and r["operations"] == 400000 and r["elapsed_ns"] > 0 for r in records)
    assert {(r["operation"], r["chains"]): r["checksum"] for r in records} == probe_checksums()
    assert validate_probes({"output/probes.jsonl": result.stdout.encode(), "output/job.status": b"0"},
                           True, hardware=True) == records


def test_probe_failure_does_not_skip_parent_shutdown(tmp_path, monkeypatch):
    from examples.boom_cost_model import prepare_probes
    captured = {}
    def compose(*a, **kw):
        captured.update(kw)
        return "composed"
    monkeypatch.setattr(prepare_probes, "FireMarshalNode", lambda: SimpleNamespace(compose=compose))
    program = SimpleNamespace(success=True, files={}, modes={})
    assert prepare_probes.compose_probe._chia_original("test", program, program) == "composed"
    command = captured["config"]["jobs"][0]["command"]
    command = command.replace("mkdir -p /output", "true").replace("/root/probes/latency-probe", "false")
    command = command.replace("/output/probes.jsonl", str(tmp_path / "stdout"))
    command = command.replace("/output/job.status", str(tmp_path / "status"))
    result = subprocess.run(["sh", "-c", command + "\nprintf 'shutdown reached\\n'"],
                            check=True, capture_output=True, text=True)
    assert (tmp_path / "status").read_text().strip() == "1"
    assert "shutdown reached" in result.stdout


@pytest.mark.parametrize("failure", ["checksum", "missing_case", "duplicate_case", "status", "counter", "simulation"])
def test_probe_validation_refuses_incomplete_or_wrong_results(failure):
    from examples.boom_cost_model.prepare_probes import probe_checksums, validate_probes
    records = [{"operation": operation, "chains": chains, "elapsed_ns": 100, "checksum": checksum,
                "correct": True, "operations": 400000}
               for (operation, chains), checksum in probe_checksums().items()]
    if failure == "checksum":
        records[0]["checksum"] += 1
    elif failure == "counter":
        records[0]["elapsed_ns"] = 0
    elif failure == "missing_case":
        records.pop()
    elif failure == "duplicate_case":
        records[-1] = records[0]
    outputs = {"output/probes.jsonl": "\n".join(json.dumps(r) for r in records).encode(),
               "output/job.status": b"1" if failure == "status" else b"0"}
    with pytest.raises(ValueError, match="probe completion"):
        validate_probes(outputs, failure != "simulation", hardware=True)


def test_content_identity_includes_permissions_scripts_and_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    file = root / "run.sh"
    file.write_text("run\n")
    a = tree_identity(root)
    file.touch()
    assert tree_identity(root) == a
    file.chmod(0o700)
    assert tree_identity(root) != a
    b = tree_identity(root)
    (root / "link").symlink_to("/outside/not/read")
    assert tree_identity(root) != b
    assert (root / "link").is_symlink()


def test_only_audited_native_compiler_environment_can_be_canonicalized(tmp_path):
    roots = [tmp_path / "original", tmp_path / "candidate"]
    for root, prefix in zip(roots, ("/original", "/candidate")):
        suite = root / "root/spec/intspeed/train"
        bench = suite / "605.mcf_s"
        bench.mkdir(parents=True)
        wrapper = Path(optimize.ROOT) / "examples/spec_build/collateral/spec2017/run_spec2017.sh"
        (suite / "intspeed.sh").write_bytes(wrapper.read_bytes())
        text = f"-E PATH /spec/bin:{prefix}/bin:/original/bin:/usr/bin\n-E RISCV {prefix}\n/spec/harness/specdiff -r 0.01 ref out\n"
        (bench / "compare.cmd").write_text(text)
        (bench / "input").write_text("fixed input")
    def identity(index):
        return tree_identity(roots[index], ("/original", "/candidate")[index])
    a, b = identity(0), identity(1)
    assert a["sha256"] == b["sha256"] and a["raw_sha256"] != b["raw_sha256"]
    assert measurement_key({"filesystem": a}, {}, "runtime", "i-a", "train", 0) == \
           measurement_key({"filesystem": b}, {}, "runtime", "i-a", "train", 0)
    path = roots[1] / "root/spec/intspeed/train/605.mcf_s/compare.cmd"
    original = path.read_text()
    for text in (original.replace("0.01", "0.1"), original.replace("/usr/bin", "/different/bin")):
        path.write_text(text)
        assert identity(1)["sha256"] != a["sha256"]
    path.write_text(original)
    wrapper = roots[1] / "root/spec/intspeed/train/intspeed.sh"
    wrapper.write_text(wrapper.read_text() + "\n# changed runtime\n")
    assert identity(1)["normalized_metadata"] == []
    assert identity(1)["sha256"] != a["sha256"]


def test_independent_repeats_workers_inputs_and_hardware_do_not_share_samples():
    def key(**kw):
        return measurement_key(**{**dict(fingerprint={"hash": "a"}, hardware={"AGFI": "a"},
            runtime_sha256="a", instance_id="i-a", inputs="train", repeat=0), **kw})
    base = key()
    assert key(fingerprint={"hash": "a", "executables": {"program": "already-in-filesystem-hash"}}) == base
    assert all(key(**change) != base for change in [{"repeat": 1}, {"instance_id": "i-b"},
        {"inputs": "ref"}, {"runtime_sha256": "b"}, {"hardware": {"AGFI": "b"}},
        {"fingerprint": {"hash": "b"}}])


def files(bench):
    return {"output/job.status": b"0\n", f"output/{bench}.status": b"0\n",
            f"output/{bench}.collection-status": b"0\n", f"output/{bench}.run.tar": b"tar",
            f"output/{bench}.csv": b"RealTime\n4.0\n"}


@pytest.mark.parametrize("fail", [False, True])
def test_two_workers_dispatch_before_wait_and_drain_after_failure(tmp_path, monkeypatch, fail):
    experiment = object.__new__(optimize.Experiment)
    experiment.config = {"benchmarks": ["a", "b"], "train_timeout_seconds": 100}
    experiment.directory = tmp_path
    (tmp_path / "config_runtime.yaml").write_text("runtime")
    experiment.hardware = {"AGFI": "agfi-a", "shell": "shell-a"}
    experiment.bitstream = experiment.run_config = None
    experiment.workers = [{"instance_id": "i-" + b, "ssh_alias": b, "current_ip": b,
                           "node_id": b * 56} for b in "ab"]
    jobs = [SimpleNamespace(json_name="job-" + b + ".json") for b in "ab"]
    workload = SimpleNamespace(json_name="all.json", split=lambda: jobs)
    fingerprints = {"job-" + b: {"hash": b} for b in "ab"}
    monkeypatch.setattr(optimize, "workload_fingerprints", SimpleNamespace(chia_remote=lambda *a: fingerprints))
    monkeypatch.setattr(optimize, "get", lambda ref: ref)
    submitted = []

    class Stage:
        def options(self, scheduling_strategy):
            node = scheduling_strategy.node_id[0]
            def remote(job, bitstream, config, timeout):
                assert timeout == 100
                submitted.append(node)
                return node
            return SimpleNamespace(chia_remote=remote)
    monkeypatch.setattr(optimize, "fpga_stage", Stage())
    def wait(refs, num_returns):
        assert len(submitted) % 2 == 0
        return [refs[0]], refs[1:]
    monkeypatch.setattr(optimize.ray, "wait", wait)
    def get(ref):
        if isinstance(ref, dict):
            return ref
        return SimJobResult("job-" + ref, success=not(fail and ref == "a"),
                            outputs=files(ref), node_id=ref * 56, ip=ref)
    monkeypatch.setattr(optimize, "get", get)
    def collect(outputs, dest, inputs, success):
        if not success:
            raise RuntimeError("simulation failed")
        for name, data in outputs.items():
            path = dest / "collected" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        optimize.save(dest / "correctness.json", {"success": True})
        return real_time(outputs)
    experiment.collect = collect
    monkeypatch.setattr(optimize.subprocess, "check_output", lambda *a, **kw: "loaded agfi-a shell-a")
    timings = {}
    if fail:
        with pytest.raises(RuntimeError, match="drained and saved"):
            experiment.measure_jobs(workload, tmp_path / "trial", "train", 0, timings)
        assert (tmp_path / "trial/job-a/failure.json").exists()
        assert (tmp_path / "trial/job-b/correctness.json").exists()
    else:
        experiment.measure_jobs(workload, tmp_path / "trial", "train", 0, timings)
        assert timings == {"a": [4.0], "b": [4.0]}
        experiment.measure_jobs(workload, tmp_path / "duplicate", "train", 0, {})
        assert submitted == ["a", "b"]
        assert json.loads((tmp_path / "duplicate/job-a/measurement.json").read_text())["reused"]
        experiment.measure_jobs(workload, tmp_path / "independent", "train", 1, {})
        assert submitted == ["a", "b", "a", "b"]
        record = next((tmp_path / "measurement-cache").glob("*.json"))
        saved = json.loads(record.read_text())
        path = Path(saved["source"]) / "collected/output/job.status"
        path.write_bytes(b"1")
        with pytest.raises(ValueError, match="bytes changed"):
            validated_cache(tmp_path / "measurement-cache", saved["key"])


def test_timeout_preserves_partial_output_and_warns_about_detached_driver(monkeypatch):
    import subprocess
    from chia.firesim.manager_node import FireSimManagerNode
    def run(*a, **kw):
        raise subprocess.TimeoutExpired("firesim", 60, output=b"partial stdout", stderr=b"partial stderr")
    monkeypatch.setattr(subprocess, "run", run)
    node = object.__new__(FireSimManagerNode)
    node.timeout_seconds = 60
    rc, log = node._firesim("runworkload")
    assert rc == -1
    assert all(s in log for s in ("partial stdout", "partial stderr", "timeout after 60s", "detached driver"))


@pytest.mark.parametrize("active,wrong_ip", [(True, False), (False, True), (False, False)])
def test_verified_pool_refuses_busy_or_mismatched_workers(monkeypatch, active, wrong_ip):
    config = {"instance_id": "i-a", "ssh_alias": "f2-a", "fpga_workers": [
        {"instance_id": "i-a", "ssh_alias": "f2-a", "ray_address": "127.0.0.2"}]}
    monkeypatch.setattr(optimize, "hardware_preflight", lambda *a: {"current_ip": "192.0.2.1"})
    monkeypatch.setattr(optimize.ray, "nodes", lambda: [{"Alive": True, "Resources": {"firesim_fpga": 1},
        "NodeID": "a" * 56, "NodeManagerAddress": "127.0.0.2"}])
    monkeypatch.setattr(optimize.subprocess, "run", lambda *a, **kw:
        SimpleNamespace(returncode=0 if active else 1))
    stage = SimpleNamespace(chia_remote=lambda: {"ip": "wrong" if wrong_ip else "192.0.2.1", "node_id": "a" * 56})
    monkeypatch.setattr(optimize, "fpga_worker_identity", SimpleNamespace(options=lambda **kw: stage))
    monkeypatch.setattr(optimize, "get", lambda ref: ref)
    if active or wrong_ip:
        with pytest.raises(RuntimeError, match="active FireSim driver" if active else "identity differ"):
            optimize.verified_workers(config, {})
    else:
        assert optimize.verified_workers(config, {})[0]["node_id"] == "a" * 56


def test_prior_evidence_excludes_reference_and_speculative_rationales(tmp_path):
    from chia.chipyard.cost_model import BASELINE_GCC_SHA256
    hardware = {k: "fixed" for k in ("AGFI", "driver_bundle_sha256", "Chipyard_revision", "FireSim_revision")}
    optimize.save(tmp_path / "hardware.json", hardware)
    optimize.save(tmp_path / "baseline-identity.json", {"drivers": {"gcc": {"sha256": BASELINE_GCC_SHA256}}})
    optimize.save(tmp_path / "baseline-f2/train/evaluation.json", {"times": {"a": 4}})
    optimize.save(tmp_path / "progress.json", {"history": [{"success": True, "train_times": {"a": 5},
        "proposal": {"costs": BASE_COSTS, "rationale": "UNPROVEN_CAUSALITY"}}]})
    optimize.save(tmp_path / "baseline-heldout/ref/evaluation.json", {"secret": "HELDOUT"})
    result = json.dumps(prior_train_evidence([str(tmp_path)], hardware))
    assert "HELDOUT" not in result and "UNPROVEN_CAUSALITY" not in result
    with pytest.raises(ValueError, match="differs"):
        prior_train_evidence([str(tmp_path)], {**hardware, "AGFI": "different"})
