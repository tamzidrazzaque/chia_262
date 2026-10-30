"""Cost-loop gates using synthetic data, without SPEC assets, AWS or Claude."""

import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from chia.chipyard.cost_model import BASE_COSTS, render_costs, validate_costs
from chia.chipyard.spec_validation import completion_status, extract_run, real_time, relative_speedup, validate_outputs
from examples.boom_cost_model.optimize import proposal


def table():
    fields = []
    for key, value in BASE_COSTS.items():
        text = "{" + ", ".join(f"COSTS_N_INSNS ({v})" for v in value) + "}" if isinstance(value, list) else str(value)
        fields.append(f"  {text}, /* {key} */")
    return "before\nstatic const struct riscv_tune_param rocket_tune_info = {\n" + "\n".join(fields) + \
           "\n  1, /* issue_rate */\n  true, /* slow_unaligned_access */\n};\nafter\n"


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, text in files.items():
            info = tarfile.TarInfo(name)
            data = text.encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def outputs():
    return {"output/job.status": b"0\n", "output/605.mcf_s.status": b"0\n",
            "output/605.mcf_s.collection-status": b"0\n", "output/605.mcf_s.run.tar": b"tar",
            "output/605.mcf_s.csv": b"name,RealTime,UserTime,KernelTime,copy\nmcf,4.0,3.0,1.0,0\n"}


def test_only_cost_fields_change():
    original = table()
    assert render_costs(original, BASE_COSTS) == original
    changed = render_costs(original, {**BASE_COSTS, "int_mul": [2, 3], "branch_cost": 6})
    assert "COSTS_N_INSNS (2), COSTS_N_INSNS (3)" in changed
    assert "6, /* branch_cost */" in changed
    assert "1, /* issue_rate */" in changed and "true, /* slow_unaligned_access */" in changed
    assert changed.startswith("before\n") and changed.endswith("after\n")


@pytest.mark.parametrize("change", [{"issue_rate": 4}, {"branch_cost": True}, {"memory_cost": 0},
                                    {"int_div": [1]}, {"int_mul": [1, 65]}, {"branch_cost": "system()"}])
def test_reject_unbounded_or_executable_values(change):
    with pytest.raises(ValueError):
        validate_costs({**BASE_COSTS, **change})


def test_proposal_requires_only_costs_and_rationale():
    good = {"costs": BASE_COSTS, "rationale": "test"}
    assert proposal(json.dumps(good)) == good
    with pytest.raises(ValueError):
        proposal(json.dumps({**good, "command": "anything"}))


@pytest.mark.parametrize("name", ["job.status", "605.mcf_s.status", "605.mcf_s.collection-status"])
@pytest.mark.parametrize("bad", [None, b"1", b""])
def test_missing_or_failed_status_prevents_scoring(name, bad):
    files = outputs()
    if bad is None:
        del files["output/" + name]
    else:
        files["output/" + name] = bad
    with pytest.raises(ValueError):
        real_time(files)


def test_exact_job_pairing_and_positive_times():
    assert real_time(outputs()) == 4
    assert relative_speedup({"a": 4, "b": 9}, {"a": 2, "b": 4.5}) == 2
    with pytest.raises(ValueError):
        relative_speedup({"a": 4}, {"b": 2})
    files = outputs()
    files["output/605.mcf_s.csv"] = b"RealTime\nnan\n"
    with pytest.raises(ValueError):
        real_time(files)


@pytest.mark.parametrize("name", ["../escape", "/absolute"])
def test_archive_traversal_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        extract_run(archive({name: "bad"}), tmp_path / "run")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("inputs,folder", [("test", "test"), ("train", "train"), ("ref", "refspeed")])
@pytest.mark.parametrize("correct", [True, False])
def test_native_comparison_applies_to_all_input_sizes(tmp_path, monkeypatch, inputs, folder, correct):
    spec = tmp_path / "spec"
    source = spec / "benchspec/CPU/605.mcf_s/run" / ("run_base_" + folder + "_host.0000")
    files = outputs()
    files["output/605.mcf_s.run.tar"] = archive({"compare.cmd": f"-C {source}\n/spec/bin/harness/specdiff ref out\n",
                                                "out": "correct" if correct else "corrupted"})
    def invoke(args, **kwargs):
        directory = kwargs["cwd"]
        assert str(source) not in (directory / "compare.collected.cmd").read_text()
        rc = 0 if (directory / "out").read_text() == "correct" else 1
        return SimpleNamespace(returncode=rc, stdout="compared", stderr="")
    monkeypatch.setattr("chia.chipyard.spec_validation.subprocess.run", invoke)
    result = validate_outputs(files, str(spec), str(tmp_path / "collected"), inputs)
    assert result["success"] == correct and result["inputs"] == inputs


def test_wrong_input_size_rejected(tmp_path):
    files = outputs()
    files["output/605.mcf_s.run.tar"] = archive({"compare.cmd": f"-C {tmp_path}/run_base_test_host.0000\n/spec/bin/harness/specdiff a b\n"})
    with pytest.raises(ValueError, match="input size"):
        validate_outputs(files, str(tmp_path), str(tmp_path / "run"), "train")


def test_explicit_compiler_pins_worker_and_environment(monkeypatch):
    from examples.spec_build import spec_sw_build_loop as software
    seen = {}
    class Build:
        def options(self, **kwargs):
            seen.update(kwargs)
            return self
        def chia_remote(self, *args, **kwargs):
            seen.update(kwargs)
            return "compiled"
    monkeypatch.setattr(software, "RiscvBuildNode", lambda **kw: SimpleNamespace(build_program=Build()))
    monkeypatch.setattr(software, "FireMarshalNode", lambda **kw: SimpleNamespace(
        build_base=SimpleNamespace(options=lambda **kw: SimpleNamespace(chia_remote=lambda *a, **kw: "base"))))
    monkeypatch.setattr(software, "_compose", SimpleNamespace(chia_remote=lambda *a: "workload"))
    result = software.start_workload("spec17-intspeed-test", compiler_prefix="/tmp/candidate", compiler_id="hash",
                                     compiler_node_id="a" * 56, benchmarks=["605.mcf_s"])
    assert result == "workload"
    assert "export RISCV=/tmp/candidate" in seen["command"][-1]
    assert 'export PATH="$RISCV/bin:$PATH"' in seen["command"][-1]
    assert seen["scheduling_strategy"].node_id == "a" * 56
    with pytest.raises(ValueError, match="compiler_node_id"):
        software.start_workload("spec17-intspeed-test", compiler_prefix="/tmp/candidate", compiler_id="hash")


@pytest.mark.parametrize("reject", [True, False])
def test_controller_gates_candidate_and_holds_reference_out(tmp_path, monkeypatch, reject):
    from examples.boom_cost_model import optimize
    from chia.chipyard.cost_model import BASELINE_GCC_SHA256
    calls = []
    class FakeExperiment:
        hardware = {"AGFI": "verified", "quintuplet": "MegaBoom", "frequency_MHz": 50}
        def __init__(self, *args):
            pass
        def compiler(self, costs=None):
            if costs is None:
                return {"drivers": {"gcc": {"sha256": BASELINE_GCC_SHA256}}}
            return {"compiler_id": "rebuilt" if costs == BASE_COSTS else "candidate",
                    "prefix": "/rebuilt" if costs == BASE_COSTS else "/candidate"}
        def evaluate(self, identity, inputs, label, qemu=False):
            calls.append((identity["prefix"], inputs, qemu))
            if reject and identity["prefix"] == "/candidate" and qemu:
                raise optimize.CandidateRejected("wrong output")
            return {"times": {"a": 2 if identity["prefix"] == "/candidate" else 4}}
    class FakeLLM:
        def __init__(self, **kwargs):
            assert kwargs["backend"] == "cli" and not kwargs["dangerously_skip_permissions"]
        def prompt(self, prompt, tools):
            assert '"inputs": "ref"' not in prompt and tools == []
            return SimpleNamespace(success=True, result=json.dumps({"costs": {**BASE_COSTS, "branch_cost": 4},
                                                                     "rationale": "bounded test"}))
    monkeypatch.setattr(optimize, "Experiment", FakeExperiment)
    monkeypatch.setattr(optimize, "ClaudeCodeLLM", FakeLLM)
    monkeypatch.setattr(optimize, "hardware_preflight", lambda *args: {})
    monkeypatch.setattr(optimize, "verified_workers", lambda *args: [])
    monkeypatch.setattr(optimize.ray, "nodes", lambda: [{"Alive": True, "Resources": {"firesim_fpga": 1}}])
    # Real constructor creates this log directory; fake keeps the test isolated.
    (tmp_path / "claude").mkdir()
    config = {"baseline_prefix": "/original", "model": "test", "iterations": 1,
              "min_improvement": 0.01, "repeats": 1, "final_ref": True, "benchmarks": ["a"]}
    optimize.run(config, tmp_path, False)
    result = json.loads((tmp_path / "result.json").read_text())
    if reject:
        assert result["best"]["prefix"] == "/original"
        assert ("/candidate", "train", False) not in calls
    else:
        assert result["best"]["prefix"] == "/candidate"
        assert result["reference_speedup"] == 2
        assert calls.index(("/candidate", "test", True)) < calls.index(("/candidate", "train", False))
    first_ref = next(i for i, c in enumerate(calls) if c[1] == "ref")
    assert all(c[1] == "ref" for c in calls[first_ref:])
    assert result["SPEC_reportable_score"] is False


@pytest.mark.parametrize("changed_network", [False, True])
def test_hardware_preflight_refuses_network_drift(monkeypatch, changed_network):
    from examples.boom_cost_model import optimize
    policy = {"IpPermissions": [], "IpPermissionsEgress": []}
    config = {"aws_account": "123", "iam_user": "operator", "instance_id": "i-existing",
              "security_group_ids": ["sg-approved"], "approved_network_policy": {"sg-approved": policy},
              "ssh_alias": "trusted-existing-f2"}
    hardware = {"AGFI": "agfi-verified", "AFI": "afi-verified", "shell": "0x10212415"}
    def fake_aws(config, *args):
        if args[:2] == ("sts", "get-caller-identity"):
            return {"Account": "123", "Arn": "arn:aws:iam::123:user/operator"}
        if args[:2] == ("ec2", "describe-instances"):
            return {"Reservations": [{"Instances": [{"State": {"Name": "running"}, "InstanceType": "f2.6xlarge",
                     "PublicIpAddress": "192.0.2.1", "SecurityGroups": [{"GroupId": "sg-approved"}]}]}]}
        if args[:2] == ("ec2", "describe-security-groups"):
            return {"SecurityGroups": [{"GroupId": "sg-approved", **policy,
                                        "IpPermissionsEgress": [{"IpProtocol": "-1"}] if changed_network else []}]}
        if args[:2] == ("ec2", "describe-fpga-images"):
            return {"FpgaImages": [{"FpgaImageId": "afi-verified", "State": {"Code": "available"}}]}
        raise AssertionError(args)
    monkeypatch.setattr(optimize, "aws", fake_aws)
    monkeypatch.setattr(optimize.subprocess, "check_output", lambda *a, **kw: "hostname 192.0.2.1\n")
    monkeypatch.setattr(optimize.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="gatewayports no\n0x10212415\n"))
    if changed_network:
        with pytest.raises(ValueError, match="network policy"):
            optimize.hardware_preflight(config, hardware)
    else:
        assert optimize.hardware_preflight(config, hardware)["current_ip"] == "192.0.2.1"
