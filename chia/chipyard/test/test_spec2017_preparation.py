"""SPEC2017 configuration and result plumbing; no licensed data required."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from examples.spec_build import spec_sw_build_loop as software
from examples.firesim_spec import spec_eval as evaluation
from chia.chipyard.state_def import ProgramBuildArtifact

COLLATERAL = software.COLLATERAL / "spec2017"
module_spec = importlib.util.spec_from_file_location("prepare_speckle", COLLATERAL / "prepare_speckle.py")
preparation = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(preparation)


def test_wrong_speckle_revision_fails_before_compiler_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *a, **k: "wrong-pin\n")
    with pytest.raises(ValueError, match="requires Speckle"):
        preparation.configure(tmp_path)
    assert not list(tmp_path.iterdir())


def test_host_configuration_keeps_target_baseline_flags(tmp_path, monkeypatch):
    directory = tmp_path / "speckle"
    directory.mkdir()
    configs = {
        "host.cfg": "% define gcc_dir %{/usr/}\n% define build_ncpus 12\nignore_errors = 1\n",
        "riscv.cfg": "% define build_ncpus 8\nignore_errors = 1\n"
                     "CC = riscv64-unknown-linux-gnu-gcc -march=rv64imafdc -mabi=lp64d -static\nOPTIMIZE = -O3\n",
        "gen_binaries.sh": 'REDIRECT=false\nbenchmarks=$(basename commands/*.cmd)\n'
                           'runcpu --action build ${suite_type}\n'
                           'runcpu --action runsetup ${suite_type}\n',
    }

    def output(args, **kwargs):
        if args[-1] == "HEAD":
            return preparation.PIN + "\n"
        if args[-1] == "--version":
            return "compiler-version\n"
        return configs[args[-1].split(":")[-1]]

    monkeypatch.setattr(preparation.subprocess, "check_output", output)
    monkeypatch.setenv("RISCV", "/unchanged/toolchain")
    monkeypatch.setattr(Path, "read_bytes", lambda path: path.name.encode())
    preparation.configure(directory)
    assert '% define gcc_dir /usr' in (directory / "host.cfg").read_text()
    target = (directory / "riscv.cfg").read_text()
    assert '-march=rv64imafdc -mabi=lp64d -static' in target and 'OPTIMIZE = -O3' in target
    assert 'build_ncpus 4' in target and 'ignore_errors = 0' in target
    assert 'REDIRECT=true' in (directory / "gen_binaries.sh").read_text()
    generated = (directory / "gen_binaries.sh").read_text()
    assert 'benchmarks="$SPEC_BENCHMARKS"' in generated
    assert generated.count('${SPEC_BENCHMARKS:-$suite_type}') == 2


def test_test_inputs_include_every_pinned_xz_case():
    jobs = software.jobs("spec17-intspeed-test")
    xz = [job for job in jobs if job["name"].startswith("657.xz_s")]
    assert len(xz) == 12
    assert all(f"--workload {i} " in job["command"] for i, job in enumerate(xz))
    assert all("CHIA_CAPTURE_OUTPUTS=1" in job["command"] and "job.status" in job["command"] for job in jobs)
    assert len([j for j in software.jobs("spec17-intspeed-ref") if j["name"].startswith("657.xz_s")]) == 2
    assert all("CHIA_CAPTURE_OUTPUTS=1" in j["command"] for j in software.jobs("spec17-intspeed-ref"))


@pytest.mark.parametrize("suite,option", [("intspeed", "--threads"), ("intrate", "--copies")])
@pytest.mark.parametrize("code", [0, 7])
def test_guest_wrapper_records_exit_status_and_separate_streams(tmp_path, suite, option, code):
    bench = tmp_path / "605.mcf_s"
    bench.mkdir()
    run = bench / "run.sh"
    run.write_text(f"#!/bin/bash\necho stdout-text; echo stderr-text >&2; exit {code}\n")
    run.chmod(0o755)
    wrapper = tmp_path / f"{suite}.sh"
    shutil.copyfile(COLLATERAL / "run_spec2017.sh", wrapper)
    output = tmp_path / "output"
    result = subprocess.run(["bash", str(wrapper), bench.name, option, "2"], cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin", "CHIA_SPEC_OUTPUT_DIR": str(output),
                                 "CHIA_CAPTURE_OUTPUTS": "1"}, capture_output=True)
    assert result.returncode == code, result.stderr
    names = [bench.name] if suite == "intspeed" else [f"{bench.name}_{i}" for i in range(2)]
    for name in names:
        assert (output / f"{name}.out").read_text() == "stdout-text\n"
        assert (output / f"{name}.err").read_text() == "stderr-text\n"
        assert (output / f"{name}.status").read_text().strip() == str(code)
        assert (output / f"{name}.collection-status").read_text().strip() == "0"
        assert (output / f"{name}.run.tar").stat().st_size > 0


def test_generated_scripts_stop_at_first_benchmark_failure(tmp_path):
    overlay = tmp_path / "build/overlay/intspeed/test/605.mcf_s"
    overlay.mkdir(parents=True)
    run = overlay / "run.sh"
    run.write_text("#!/bin/bash\nfalse\necho incorrect-success\n")
    preparation.finish(tmp_path, "intspeed", "test")
    result = subprocess.run(["bash", str(run)], capture_output=True, text=True)
    assert result.returncode != 0 and "incorrect-success" not in result.stdout


def test_guest_collection_failure_is_not_a_benchmark_success(tmp_path):
    benchmark = tmp_path / "605.mcf_s"
    benchmark.mkdir()
    run = benchmark / "run.sh"
    run.write_text("#!/bin/bash\nexit 0\n")
    run.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    tar = tools / "tar"
    tar.write_text("#!/bin/sh\necho collection-failed >&2\nexit 17\n")
    tar.chmod(0o755)
    wrapper = tmp_path / "intspeed.sh"
    shutil.copyfile(COLLATERAL / "run_spec2017.sh", wrapper)
    output = tmp_path / "output"
    result = subprocess.run(["bash", str(wrapper), benchmark.name], cwd=tmp_path,
                            env={"PATH": f"{tools}:/usr/bin:/bin", "CHIA_CAPTURE_OUTPUTS": "1",
                                 "CHIA_SPEC_OUTPUT_DIR": str(output)}, capture_output=True)
    assert result.returncode == 17
    assert (output / "605.mcf_s.status").read_text().strip() == "0"
    assert (output / "605.mcf_s.collection-status").read_text().strip() == "17"
    assert b"collection-failed" in result.stderr


@pytest.mark.parametrize("success,status", [(False, b"0"), (True, b"7"), (True, b"0")])
def test_score_checks_simulation_and_guest_status(success, status):
    result = SimpleNamespace(success=success, outputs={
        "output/reftimes.json": b'{"605.mcf_s": 100}',
        "output/605.mcf_s.csv": b'name,RealTime,UserTime,KernelTime,copy\n605.mcf_s,10,0,0,0\n',
        "output/job.status": status,
    })
    _, _, score = evaluation._score([result])
    assert (score == pytest.approx(10)) if success and status == b"0" else score is None


def test_collection_failure_prevents_score():
    result = SimpleNamespace(success=True, outputs={
        "job/output/reftimes.json": b'{"605.mcf_s": 100}',
        "job/output/605.mcf_s.csv": b'name,RealTime,UserTime,KernelTime\n605.mcf_s,10,0,0\n',
        "job/output/605.mcf_s.collection-status": b"1",
    })
    assert evaluation._score([result])[2] is None


def test_missing_job_outputs_prevent_partial_score():
    good = SimpleNamespace(success=True, outputs={
        "job/output/reftimes.json": b'{"605.mcf_s": 100}',
        "job/output/605.mcf_s.csv": b'name,RealTime,UserTime,KernelTime\n605.mcf_s,10,0,0\n',
    })
    assert evaluation._score([good, SimpleNamespace(success=True, outputs={})])[2] is None


def test_spec2017_build_retains_comparison_inputs_and_diagnostics(monkeypatch):
    calls = []
    monkeypatch.setattr(software, "RiscvBuildNode", lambda **kw: SimpleNamespace(
        build_program=SimpleNamespace(chia_remote=lambda *a, **kw: calls.append(kw))))
    base = SimpleNamespace(chia_remote=lambda *a, **kw: None)
    base.options = lambda **kw: base
    monkeypatch.setattr(software, "FireMarshalNode", lambda **kw: SimpleNamespace(build_base=base))
    monkeypatch.setattr(software, "_compose", SimpleNamespace(chia_remote=lambda *a: None))
    software.start_workload("spec17-intspeed-test", compiler_id="pinned-image")
    call = calls[0]
    assert call["outputs"] == ["root", "build-logs"]
    assert call["cleanup_task_dir"] is False
    command = call["command"][-1]
    assert 'trap ' in command and 'compiler-provenance.json' in command
    assert 'rm -rf "$SPEC_DIR"' not in command
    assert 'SPEC_DIR_2017' in command


def test_functional_subset_compiles_and_composes_only_selected_benchmarks(monkeypatch):
    calls = []
    composed = []
    monkeypatch.setattr(software, "RiscvBuildNode", lambda **kw: SimpleNamespace(
        build_program=SimpleNamespace(chia_remote=lambda *a, **kw: calls.append(kw))))
    base = SimpleNamespace(chia_remote=lambda *a, **kw: None)
    base.options = lambda **kw: base
    monkeypatch.setattr(software, "FireMarshalNode", lambda **kw: SimpleNamespace(build_base=base))
    monkeypatch.setattr(software, "_compose", SimpleNamespace(chia_remote=lambda *args: composed.append(args)))
    software.start_workload("spec17-intspeed-test", compiler_id="pinned",
                            benchmarks=["605.mcf_s", "648.exchange2_s"])
    assert "export SPEC_BENCHMARKS='605.mcf_s 648.exchange2_s'" in calls[0]["command"][-1]
    assert {j["name"] for j in composed[0][3]} == {"605.mcf_s", "648.exchange2_s"}


@pytest.mark.parametrize("spec,benchmarks", [("spec17-intspeed-test", []),
                                            ("spec17-intspeed-test", ["not-a-benchmark"]),
                                            ("spec06-int-test", ["605.mcf_s"])])
def test_invalid_subset_is_rejected_before_build(spec, benchmarks):
    with pytest.raises(ValueError, match="existing SPEC2017"):
        software.start_workload(spec, benchmarks=benchmarks)


def test_failed_spec_build_diagnostics_survive_compose(tmp_path, monkeypatch):
    monkeypatch.setattr(software, "Path", lambda value: tmp_path if value == "/images" else Path(value))
    spec = ProgramBuildArtifact({"build-logs/riscv-build.log": b"compile failed"},
                                False, "native setup", "compiler error", 7)
    result = software._compose._chia_original("spec17-intspeed-test-example", spec,
                                              SimpleNamespace(success=True), [], False, "")
    assert not result.success and "compiler error" in result.stderr
    logs = tmp_path / "spec17-intspeed-test-example-build-logs"
    assert (logs / "compiler.stdout").read_text() == "native setup"
    assert (logs / "compiler.stderr").read_text() == "compiler error"
    assert (logs / "riscv-build.log").read_bytes() == b"compile failed"


@pytest.mark.parametrize("success", [False, True])
def test_build_cli_records_workload_and_failure(tmp_path, monkeypatch, success):
    monkeypatch.setattr(software.sys, "argv", ["spec_sw_build_loop.py", "spec17-intspeed-test",
                        "--output-dir", str(tmp_path), "--compiler-id", "pinned-compiler", "--small-images"])
    monkeypatch.setattr(software, "driver_options", lambda address: {"address": address})
    monkeypatch.setattr(software.ray, "init", lambda **kw: None)
    calls = []
    monkeypatch.setattr(software, "start_workload", lambda *a, **kw: calls.append(kw))
    workload = SimpleNamespace(success=success, stdout="build log", stderr="diagnostic",
                               returncode=0 if success else 7, json_name="workload.json", archive=b"archive")
    monkeypatch.setattr(software, "get", lambda ref: workload)
    assert software.main() == (0 if success else 1)
    metadata = json.loads((tmp_path / "build.json").read_text())
    assert metadata["success"] is success
    assert metadata["compiler_id"] == "pinned-compiler"
    assert metadata["spec_flags"] == ""
    assert metadata["QEMU_validated"] is False
    assert (tmp_path / "build.stderr").read_text() == "diagnostic"
    assert (tmp_path / "workload.tar.gz").exists() is success
    assert calls[0]["compiler_id"] == "pinned-compiler"
    assert calls[0]["small_images"] is True and metadata["small_images"] is True
