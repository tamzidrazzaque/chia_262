"""Validate daemon-free staging and Docker's imported image identity."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from examples.firesim_spec import stage_existing_f2 as staging
from examples.firesim_spec import prepare_cluster as preparation


def _archive(path, config=b'{"architecture":"amd64"}', count=1):
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = [{"Config": "config.json", "RepoTags": None, "Layers": []}] * count
    with tarfile.open(path, "w") as archive:
        for name, data in [("config.json", config),
                           ("manifest.json", json.dumps(manifest).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return config_id


def test_archive_must_match_pinned_config(tmp_path):
    archive = tmp_path / "image.tar"
    image = _archive(archive)
    staging.validate_image_archive(archive, image)
    with pytest.raises(ValueError, match="does not match"):
        staging.validate_image_archive(archive, "sha256:" + "f" * 64)


@pytest.mark.parametrize("count", [0, 2])
def test_archive_cannot_stage_multiple_images(tmp_path, count):
    archive = tmp_path / "image.tar"
    image = _archive(archive, count=count)
    with pytest.raises(ValueError, match="exactly one image"):
        staging.validate_image_archive(archive, image)


@pytest.mark.parametrize("output", ["", "Loaded image: example:latest\n",
                                    "Loaded image ID: sha256:abc\n",
                                    ("Loaded image ID: sha256:" + "a" * 64 + "\n") * 2])
def test_load_requires_one_immutable_runtime_id(output):
    with pytest.raises(ValueError, match="exactly one image ID"):
        staging.loaded_image_id(output)


def test_cached_cluster_checks_local_images_without_pulling_firesim(tmp_path, monkeypatch):
    images = {name: "sha256:" + digit * 64 for name, digit in
              [("riscv_build", "a"), ("firemarshal", "b"), ("firesim", "c")]}
    images["firesim_archive_config_id"] = "sha256:" + "d" * 64
    path = tmp_path / "images.json"
    path.write_text(json.dumps(images))
    run = Mock(return_value="3.10.19 2.54.0")
    monkeypatch.setattr(preparation, "_run", run)
    assert preparation.cached_images(path) == images
    assert run.call_count == 2
    commands = [call.args[0] for call in run.call_args_list]
    assert all("--pull" in args and "never" in args and "none" in args for args in commands)
    assert all(images["firesim"] not in args for args in commands)
    run.return_value = "3.10.19 2.53.0"
    with pytest.raises(RuntimeError, match="expected Python"):
        preparation.cached_images(path)


def test_cached_cluster_rejects_mutable_image_before_docker(tmp_path, monkeypatch):
    path = tmp_path / "images.json"
    path.write_text(json.dumps({"riscv_build": "example:latest"}))
    run = Mock()
    monkeypatch.setattr(preparation, "_run", run)
    with pytest.raises(ValueError, match="immutable Docker image ID"):
        preparation.cached_images(path)
    run.assert_not_called()


@pytest.mark.parametrize("year", [2006, 2017])
def test_preparation_stages_private_token_outside_nfs_home(tmp_path, monkeypatch, year):
    home = tmp_path / "nfs-home"
    token = home / ".config/chia-research/ray.token"
    token.parent.mkdir(parents=True)
    token.write_text("test-ray-token\n")
    token.chmod(0o600)
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "shrc").write_text("")
    if year == 2006:
        (spec / "benchspec/CPU2006").mkdir(parents=True)
    else:
        (spec / "bin").mkdir()
        (spec / "bin/runcpu").write_text("fixture")
        (spec / "benchspec/CPU/605.mcf_s").mkdir(parents=True)
        (spec / "benchspec/CPU/648.exchange2_s").mkdir()
    key = tmp_path / "test-key"
    key.write_text("unit-test placeholder")
    output = tmp_path / "scratch-run"
    images = {name: "sha256:" + "a" * 64 for name in preparation.IMAGES}
    monkeypatch.setattr(preparation.Path, "home", lambda: home)
    argv = ["prepare_cluster.py", "--spec-dir", str(spec), "--spec-year", str(year),
            "--output", str(output), "--ssh-key", str(key),
            "--images-json", str(tmp_path / "cached-images.json")]
    if year == 2006:
        argv += ["--f2-ip", "192.0.2.10"]
    monkeypatch.setattr(preparation, "sys", SimpleNamespace(
        argv=argv,
        version_info=(3, 10, 19), executable=sys.executable))
    monkeypatch.setattr(sys, "argv", preparation.sys.argv)
    monkeypatch.setattr(preparation, "cached_images", lambda path: images)
    run = Mock()
    monkeypatch.setattr(preparation.subprocess, "run", run)
    assert preparation.main() == 0
    local = output / "ray.token"
    assert local.read_bytes() == token.read_bytes() == b"test-ray-token\n"
    assert local.stat().st_mode & 0o777 == 0o600
    assert (output / "compiler-home").stat().st_mode & 0o777 == 0o700
    assert (output / "compiler-builds").stat().st_mode & 0o777 == 0o700
    config = json.loads((output / "cluster.yaml").read_text())
    for name in ("riscv_build", "firemarshal"):
        assert f"-v {local}:/run/chia/ray.token:ro" in config["available_node_types"][name]["docker"]["run_options"]
    docker_calls = [c.args[0] for c in run.call_args_list
                    if isinstance(c.args[0], list) and c.args[0][0] == "docker"]
    assert docker_calls[0] == ["docker", "info"]
    assert len(docker_calls) == 2
    assert "none" in docker_calls[1] and "/usr/bin/gcc" in docker_calls[1]
    assert config["auth"]["strict_host_key_checking"] is True
    assert config["auth"]["forward_agent"] is False
    assert "python -m chia.cluster.loopback" in config["head_start_ray_commands"]
    assert "python -m chia.cluster.loopback" in config["worker_start_ray_commands"]
    options = config["available_node_types"]["riscv_build"]["docker"]["run_options"]
    assert f"-e SPEC_DIR_{year}={spec}" in options
    assert f"-e SPEC_DIR={spec}" in options
    assert f"export SPEC_DIR={spec}" in (output / "env.sh").read_text()
    assert f"-v {output / 'compiler-builds'}:/tmp/spec_build" in options
    assert ("firesim" in config["available_node_types"]) == (year == 2006)


@pytest.mark.parametrize("year", ["2017", "2026"])
def test_preparation_refuses_a_different_spec_suite(tmp_path, monkeypatch, year):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "shrc").write_text("")
    (spec / f"benchspec/CPU{year}").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["prepare_cluster.py", "--spec-dir", str(spec)])
    docker = Mock(side_effect=AssertionError("invalid suite must not start containers"))
    monkeypatch.setattr(preparation.subprocess, "run", docker)
    with pytest.raises(SystemExit) as exc:
        preparation.main()
    assert exc.value.code == 2
    docker.assert_not_called()


def test_spec2017_install_validation_and_mount(tmp_path):
    spec = tmp_path / "spec2017"
    spec.mkdir()
    for marker in ("shrc", "bin/runcpu"):
        path = spec / marker
        path.parent.mkdir(exist_ok=True)
        path.write_text("test fixture")
    (spec / "benchspec/CPU/605.mcf_s").mkdir(parents=True)
    with pytest.raises(ValueError, match="648.exchange2_s"):
        preparation.validate_spec_install(spec, 2017)
    (spec / "benchspec/CPU/648.exchange2_s").mkdir()
    preparation.validate_spec_install(spec, 2017)
    config = preparation.make_config(spec, tmp_path, tmp_path / "token",
                                     preparation.IMAGES, tmp_path / "python", None,
                                     tmp_path / "key", spec_year=2017)
    options = config["available_node_types"]["riscv_build"]["docker"]["run_options"]
    assert f"-v {spec}:{spec}" in options
    assert f"-e SPEC_DIR_2017={spec}" in options
    assert not any("SPEC_DIR_2006" in option for option in options)
    assert "firesim" not in config["available_node_types"]
    assert all("@sha256:" in image for image in preparation.IMAGES.values())


def test_gatewayports_no_requires_verified_owned_loopback_relay(tmp_path):
    ready = Path("/home/ubuntu/chia-setup/loopback-relay-1234abcd/ready.json")
    config = preparation.make_config(tmp_path, tmp_path, tmp_path / "token",
                                     preparation.IMAGES, tmp_path / "python", "192.0.2.1",
                                     tmp_path / "key", 2017, ready)
    command = config["auth"]["overrides"]["192.0.2.1"]["tunnel"]["pre_tunnel_commands"][0]
    assert 'elif test "$policy" = no' in command
    assert "loopback_relay.py" in command and "--check" in command
    assert str(ready) in command
    assert "sshd_config" not in command and "sysctl" not in command and "iptables" not in command
    with pytest.raises(ValueError, match="private owned"):
        preparation.make_config(tmp_path, tmp_path, tmp_path / "token", preparation.IMAGES,
                                tmp_path / "python", "192.0.2.1", tmp_path / "key", 2017,
                                Path("/tmp/foreign/ready.json"))


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("version", ["3.10.19 2.54.0", "3.10.18 2.54.0"])
def test_archive_staging_uses_f2_runtime_id_without_local_docker(tmp_path, monkeypatch, cached, version):
    archive = tmp_path / "image.tar"
    config_id = _archive(archive)
    runtime_id = "sha256:" + "b" * 64
    images = {"firesim": runtime_id if cached else config_id,
              "firesim_archive_config_id": config_id}
    (tmp_path / "images.json").write_text(json.dumps(images))
    cluster = {"available_node_types": {"firesim": {"docker": {"image": images["firesim"]}}}}
    (tmp_path / "cluster.yaml").write_text(json.dumps(cluster))
    token = tmp_path / ".config/chia-research/ray.token"
    token.parent.mkdir(parents=True)
    token.write_text("test-token\n")
    monkeypatch.setattr(staging.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["stage_existing_f2.py", "--f2-ip", "192.0.2.10",
                                     "--output", str(tmp_path), "--image-archive", str(archive)])
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if cached or "docker image inspect" not in args[-1] else 1)

    def output(args, **kwargs):
        calls.append(args)
        if args[-1] == "docker load":
            assert kwargs["stdin"].read(1)
            return "Loaded image ID: " + runtime_id + "\n"
        assert runtime_id in args[-1]
        assert "--network none --pull never" in args[-1]
        return version + "\n"

    monkeypatch.setattr(staging.subprocess, "run", run)
    monkeypatch.setattr(staging.subprocess, "check_output", output)
    sdk = Mock()
    monkeypatch.setattr(staging, "stage_sdk", sdk)
    if version != "3.10.19 2.54.0":
        with pytest.raises(RuntimeError, match="expected Python 3.10.19 and Ray 2.54.0"):
            staging.main()
        sdk.assert_not_called()
        return
    staging.main()
    assert all(args[0] in ("ssh", "scp") for args in calls)
    assert sum(args[-1] == "docker load" for args in calls) == (0 if cached else 1)
    sdk.assert_called_once()
    assert sdk.call_args.args[1] == runtime_id
    assert json.loads((tmp_path / "images.json").read_text())["firesim"] == runtime_id
    assert json.loads((tmp_path / "cluster.yaml").read_text())["available_node_types"]["firesim"]["docker"]["image"] == runtime_id
