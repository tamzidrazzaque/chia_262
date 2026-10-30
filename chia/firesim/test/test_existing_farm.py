"""Offline checks for the existing-F2 SPEC evaluation path and compiler cache."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from chia.aws.manager import Farm
from chia.cluster.config import build_config, assign_nodes
from chia.cluster.node_setup import allocate_worker_tunnels, build_worker_script
from examples.firesim_spec import spec_eval as evaluation
from examples.firesim_spec.prepare_cluster import make_config
from examples.spec_build import spec_sw_build_loop as software


def _workload(monkeypatch):
    workload = SimpleNamespace(success=True)
    monkeypatch.setattr(evaluation.spec_build, "jobs", lambda *a: [{"name": "job"}])
    monkeypatch.setattr(evaluation, "get", lambda value: value)
    monkeypatch.setattr(evaluation, "_score", lambda jobs: ({}, {}, 1.0))
    return workload


def test_existing_worker_runs_without_ec2_launch_or_teardown(monkeypatch):
    workload = _workload(monkeypatch)
    farm = Farm("firesim", "us-east-1", ["192.0.2.10"])
    bitstream = SimpleNamespace(driver_uri=None)
    manager = SimpleNamespace(run_workload=Mock(return_value=[]))
    monkeypatch.setattr(evaluation, "FireSimManagerNode", lambda: manager)
    monkeypatch.setattr(Farm, "teardown", Mock(side_effect=AssertionError("must not terminate an existing instance")))
    result = evaluation.spec_eval._chia_original(
        None, "spec06-int-test", None, bitstream=bitstream, workload=workload,
        existing_farm=farm, max_fpgas=1)
    assert result.score == 1.0
    manager.run_workload.assert_called_once_with(farm, workload, bitstream, None)


def test_existing_worker_is_retained_when_simulation_fails(monkeypatch):
    workload = _workload(monkeypatch)
    monkeypatch.setattr(evaluation, "FireSimManagerNode", lambda: SimpleNamespace(
        run_workload=Mock(side_effect=RuntimeError("simulation failed"))))
    monkeypatch.setattr(Farm, "teardown", Mock(side_effect=AssertionError("must not terminate")))
    with pytest.raises(RuntimeError, match="simulation failed"):
        evaluation.spec_eval._chia_original(
            None, "spec06-int-test", None, bitstream=SimpleNamespace(driver_uri=None),
            workload=workload, existing_farm=Farm("firesim", "us-east-1", ["192.0.2.10"]))


def test_existing_worker_cannot_trigger_a_hardware_build():
    with pytest.raises(ValueError, match="prebuilt bitstream"):
        evaluation.spec_eval._chia_original(
            None, "spec06-int-test", None,
            existing_farm=Farm("firesim", "us-east-1", ["192.0.2.10"]))


@pytest.mark.parametrize("farm", [Farm("firesim", "us-east-1", []),
                                  Farm("firesim", "us-east-1", ["192.0.2.10"], manager=object())])
def test_invalid_existing_farm_is_rejected_before_building(farm):
    with pytest.raises(ValueError, match="workers and no lifecycle manager"):
        evaluation.spec_eval._chia_original(None, "spec06-int-test", None,
                                            bitstream=object(), existing_farm=farm)


def test_auto_provisioning_keeps_its_lifecycle(monkeypatch):
    workload = _workload(monkeypatch)
    farm = SimpleNamespace(teardown=Mock())
    aws = SimpleNamespace(launch=SimpleNamespace(chia_remote=Mock(return_value=farm)))
    monkeypatch.setattr(evaluation, "FireSimManagerNode", lambda: SimpleNamespace(
        run_workload=Mock(return_value=[])))
    evaluation.spec_eval._chia_original(aws, "spec06-int-test", None,
                                        bitstream=SimpleNamespace(driver_uri=None),
                                        workload=workload, max_fpgas=1)
    assert aws.launch.chia_remote.call_args.kwargs["count"] == 1
    farm.teardown.assert_called_once()


def test_compiler_change_rebuilds_even_with_identical_flags(monkeypatch):
    monkeypatch.setattr(software, "RiscvBuildNode", lambda **kw: SimpleNamespace(
        build_program=SimpleNamespace(chia_remote=lambda *a, **k: "compiled")))
    option = SimpleNamespace(chia_remote=lambda *a, **k: "base")
    option.options = lambda **kw: option
    monkeypatch.setattr(software, "FireMarshalNode", lambda **kw: SimpleNamespace(build_base=option))
    monkeypatch.setattr(software, "_compose", SimpleNamespace(chia_remote=lambda name, *args: name))
    first = software.start_workload("spec06-int-test", spec_flags="-mtune=rocket", compiler_id="gcc-a")
    same = software.start_workload("spec06-int-test", spec_flags="-mtune=rocket", compiler_id="gcc-a")
    changed = software.start_workload("spec06-int-test", spec_flags="-mtune=rocket", compiler_id="gcc-b")
    assert first == same
    assert first != changed


def test_generated_cluster_routes_custom_head_port_and_uses_token_auth(monkeypatch):
    # Live lab tunnels must not affect this generated-config unit test.
    monkeypatch.setattr("chia.cluster.node_setup._foreign_tunnel_binds", lambda own_ips: set())
    raw = make_config(Path("/scratch/chia-research/spec2006"), Path("/scratch/chia-research/run"),
                      Path("/home/researcher/.config/chia-research/ray.token"),
                      {k: f"ghcr.io/ucb-bar/{k}@sha256:abc" for k in ("riscv_build", "firemarshal", "firesim")},
                      Path("/scratch/chia-research/chia-env/bin/python"), "192.0.2.10",
                      Path("/home/researcher/.ssh/chia_research_aws.pem"))
    assert "aws_nodes" not in raw
    config = build_config(raw)
    assert config.head_ray_address == "127.200.0.1:22379"
    assert any("--dashboard-host=127.0.0.1" in cmd for cmd in raw["head_start_ray_commands"])
    assert "export RAY_AUTH_MODE=token" in config.head_env_commands
    compiler_options = raw["available_node_types"]["riscv_build"]["docker"]["run_options"]
    assert "--group-add 100" in compiler_options
    assert "-v /scratch/chia-research/run/compiler-home:/home/chia-compiler" in compiler_options
    assert "-e HOME=/home/chia-compiler" in compiler_options
    tunnel_options = raw["auth"]["overrides"]["192.0.2.10"]["tunnel"]
    checks = tunnel_options["pre_tunnel_commands"]
    assert len(checks) == 1 and "sshd -T" in checks[0]
    assert all(word not in checks[0] for word in ("restart", "sed -i", "sysctl", "iptables"))
    assert tunnel_options["kill_orphaned_tunnels"] is False
    assignments = assign_nodes(config)
    tunnels = allocate_worker_tunnels(config, assignments)
    worker = next(a for a in assignments if a.node_type.name == "firesim")
    script = build_worker_script(config, worker,
                                 tunnel_config=tunnels[(worker.ip, worker.node_type.name, worker.worker_index)],
                                 head_ip=config.head_ip)
    command = next(c for c in script if "ray start" in c)
    assert "--address=127.0.0.2:23379" in command
    assert "$RAY_HEAD_IP:22379" not in command
    assert "export RAY_AUTH_MODE=token" in script
    assert "export RAY_AUTH_TOKEN_PATH=/run/chia/ray.token" in script
    assert "export PYTHONPATH=/opt/chia-research:$PYTHONPATH" in script
    assert Path(raw["file_mounts"]["/tmp/chia-research-chia-source"]).resolve() == Path(__file__).resolve().parents[3]
    assert {".setup/", "*.pem", ".env", "*.apikey"} <= set(raw["rsync_exclude"])
    for node in raw["available_node_types"].values():
        assert "-v /tmp/chia-research-chia-source:/opt/chia-research:ro" in node["docker"]["run_options"]
