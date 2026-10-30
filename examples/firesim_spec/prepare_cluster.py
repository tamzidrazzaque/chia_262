"""Prepare a SPEC2006/2017 cluster on the lab host with an optional existing F2.

Run with the Python interpreter in the installed Chia environment. Docker
images are pulled on the lab host only when not cached, then pinned to digests.
This program does not launch AWS instances or start Ray.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

IMAGES = {
    "riscv_build": "ghcr.io/ucb-bar/chia-riscv-cross@sha256:98ec34c882e3a0644ebffea3ea93375ebf3738c3e11f7c6605a7a1bbd70952ab",
    "firemarshal": "ghcr.io/ucb-bar/chia-firemarshal@sha256:1f8ec993a5259101799212b0efcd6ecd618fa73f330ad54d9483b19a8e5fd22f",
    "firesim": "ghcr.io/ucb-bar/chia-firesim@sha256:d421a98076338afecef1b6020719645678589cb4b41bd8c0783cc98de20090c8",
}


def _run(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def pin_image(image: str) -> str:
    """Resolve a cached or freshly pulled image to an immutable repository digest."""
    result = subprocess.run(["docker", "image", "inspect", image],
                            capture_output=True, text=True)
    if result.returncode:
        subprocess.run(["docker", "pull", image], check=True)
    data = json.loads(_run(["docker", "image", "inspect", image]))[0]
    repo = image.split("@", 1)[0]
    digests = [d for d in data.get("RepoDigests", []) if d.startswith(repo + "@sha256:")]
    if not digests:
        raise RuntimeError(f"{image} has no repository digest; use a published image")
    version = _run(["docker", "run", "--rm", "--entrypoint", "python", digests[0],
                    "-c", "import sys,ray; print('.'.join(map(str,sys.version_info[:3])),ray.__version__)"])
    if version != "3.10.19 2.54.0":
        raise RuntimeError(f"{image} uses {version}; expected Python 3.10.19 and Ray 2.54.0")
    return digests[0]


def cached_images(path: Path) -> dict[str, str]:
    """Read imported image IDs, checking the two the lab host worker runtimes.

    Args:
        path: JSON file containing immutable IDs for each worker image.
    """
    images = json.loads(path.read_text())
    for name in IMAGES:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", images.get(name, "")):
            raise ValueError(f"{name} must have an immutable Docker image ID")
    for name in ("riscv_build", "firemarshal"):
        version = _run(["docker", "run", "--rm", "--network", "none", "--pull", "never",
                        "--entrypoint", "python", images[name], "-c",
                        "import sys,ray; print('.'.join(map(str,sys.version_info[:3])),ray.__version__)"])
        if version != "3.10.19 2.54.0":
            raise RuntimeError(f"{name} uses {version}; expected Python 3.10.19 and Ray 2.54.0")
    # FireSim is already staged on F2; stage_existing_f2 checks its runtime.
    return images


def make_config(spec_dir: Path, output: Path, token: Path, images: dict[str, str],
                python: Path, f2_ip: str | None, key: Path, spec_year: int = 2006,
                ssh_loopback_relay_ready: Path | None = None) -> dict:
    """Return configuration with separate ports, token auth, and fixed workers."""
    if spec_year not in (2006, 2017):
        raise ValueError("SPEC year must be 2006 or 2017")
    head = "127.200.0.1"
    source_dir = Path(__file__).resolve().parents[2]
    source_host = "/tmp/chia-research-chia-source"
    source_mount = f"-v {source_host}:/opt/chia-research:ro"
    runtime_host = "/tmp/chia-research-runtime"
    guard_mount = f"-v {runtime_host}/loopback-bind.so:/run/chia/loopback-bind.so:ro"
    auth_commands = ["unset RAY_AUTH_TOKEN", "export RAY_AUTH_MODE=token",
                     "export RAY_AUTH_TOKEN_PATH=/run/chia/ray.token",
                     "export PYTHONPATH=/opt/chia-research:$PYTHONPATH",
                     "export LD_PRELOAD=/run/chia/loopback-bind.so",
                     "export CHIA_LOOPBACK_BIND_IP=127.200.0.1"]
    token_mount = f"-v {token}:/run/chia/ray.token:ro"
    nodes = {
        "riscv_build": {
            "resources": {"riscv_build": 4}, "num_workers": 1, "compatible_ips": [head],
            "worker_env_commands": auth_commands,
            "docker": {
                "image": images["riscv_build"], "container_name": "chia-research-compiler",
                "pull_before_run": False,
                "run_options": ["--ulimit nofile=65536:65536", "--cpus=4", "--memory=16g",
                                f"--user {os.getuid()}:{os.getgid()}", "--group-add 100",
                                f"-v {output / 'compiler-home'}:/home/chia-compiler",
                                f"-v {output / 'compiler-builds'}:/tmp/spec_build",
                                "-e HOME=/home/chia-compiler", token_mount, source_mount, guard_mount,
                                f"-v {spec_dir}:{spec_dir}", f"-e SPEC_DIR_{spec_year}={spec_dir}",
                                f"-e SPEC_DIR={spec_dir}"],
            },
        },
        "firemarshal": {
            "resources": {"firemarshal": 1}, "num_workers": 1, "compatible_ips": [head],
            "worker_env_commands": auth_commands,
            "docker": {
                "image": images["firemarshal"], "container_name": "chia-research-firemarshal",
                "pull_before_run": False,
                "run_options": ["--privileged", "--user root", "--cpus=4", "--memory=16g",
                                token_mount, source_mount, guard_mount,
                                f"-v {output / 'fm-images'}:/images"],
            },
        },
    }
    overrides = {}
    if f2_ip:
        relay_check = ""
        if ssh_loopback_relay_ready is not None:
            relay_dir = str(ssh_loopback_relay_ready.parent)
            if not re.fullmatch(r"/home/ubuntu/chia-setup/loopback-relay-[0-9a-f]{8}", relay_dir):
                raise ValueError("Expected a private owned F2 loopback-relay directory")
            if ssh_loopback_relay_ready.name != "ready.json":
                raise ValueError("Expected the relay's ready.json")
            relay_check = (f"elif test \"$policy\" = no; then python3 {relay_dir}/loopback_relay.py "
                           f"--config {relay_dir}/mappings.json --ready {relay_dir}/ready.json --check; ")
        nodes["firesim"] = {
            "resources": {"firesim_fpga": 1}, "num_workers": 1, "compatible_ips": [f2_ip],
            "worker_env_commands": auth_commands + ["export CHIA_LOOPBACK_BIND_IP=127.0.0.2",
                                                     "export CHIA_FIRESIM_SKIP_DEBUG_SERVERS=1",
                                                     "export CHIA_FIRESIM_PREPARED_SDK_REVISION=434775d5fc098d08b100dd5494302e84ba2165a4"],
            "docker": {
                "image": images["firesim"], "container_name": "chia-research-firesim",
                "pull_before_run": False,
                "run_options": ["--privileged", "--pid=host", "--cpus=4", "--memory=32g",
                                source_mount, guard_mount,
                                "-v /home/ubuntu:/home/ubuntu:rslave",
                                "-v /home/ubuntu/chia-setup/results:/home/ray/firesim/deploy/results-workload",
                                "-v /home/ubuntu/chia-setup/manager-logs:/home/ray/firesim/deploy/logs",
                                "-v /home/ubuntu/chia-setup/ray.token:/run/chia/ray.token:ro"],
            },
        }
        overrides[f2_ip] = {"ssh_user": "ubuntu", "ssh_private_key": str(key),
                           "tunnel": {"pre_tunnel_commands": [
                               # GatewayPorts=no needs verified owned alias relays.
                               # GatewayPorts=yes permits wildcard binds and is refused.
                               "policy=$(sudo -n /usr/sbin/sshd -T -C "
                               "user=ubuntu,host=millennium,addr=169.229.49.43 | "
                               "awk '$1 == \"gatewayports\" {print $2}'); "
                               "if test \"$policy\" = clientspecified; then :; " + relay_check +
                               "else echo 'Requires clientspecified or verified owned loopback relays; SSH policy was not changed' >&2; exit 1; fi"
                               "; for dir in /home/ubuntu/chia-setup/results /home/ubuntu/chia-setup/manager-logs; "
                               "do test ! -L \"$dir\" && mkdir -p -m 700 \"$dir\" && test -O \"$dir\" || exit 1; done"
                           ], "kill_orphaned_tunnels": False,
                                      "gcs_tunnel_port": 23379,
                                      "ray_node_manager_port": 23400,
                                      "ray_object_manager_port": 23401,
                                      "ray_worker_port_min": 23500, "ray_worker_port_max": 23531,
                                      "tool_port_min": 23600, "tool_port_max": 23610,
                                      "head_tool_port_min": 23700, "head_tool_port_max": 23710,
                                      "head_node_manager_port": 22900, "head_object_manager_port": 22901,
                                      "head_worker_port_min": 23000, "head_worker_port_max": 23099}}
    return {
        "cluster_name": "chia-research", "provider": {"head_ip": head},
        "auth": {"ssh_user": os.environ.get("USER", "researcher"), "overrides": overrides,
                 "strict_host_key_checking": True, "forward_agent": False},
        "available_node_types": nodes, "scoped_teardown": True,
        # Published images can predate this fork. Sync only source, excluding
        # local downloads and private files, before starting container workers.
        "file_mounts": {source_host: str(source_dir) + "/",
                        runtime_host: str(output / "runtime") + "/"},
        "rsync_exclude": [".git/", ".setup/", "__pycache__/", "*.pyc", "*.pem",
                          ".env", "*.apikey", "outputs/", "out/", "tmp/", "*.egg-info/"],
        "head_env_commands": [f"export PATH={shlex.quote(str(python.parent))}:$HOME/.local/bin:$PATH",
                              "export RAY_AUTH_MODE=token",
                              "unset RAY_AUTH_TOKEN",
                              f"export RAY_AUTH_TOKEN_PATH={shlex.quote(str(token))}",
                              "export CHIA_TOOL_ADVERTISE_HOST=127.200.0.1",
                              "export CHIA_TOOL_BASE_PORT=23700",
                              "export CHIA_TOOL_MAX_PORT=23710",
                              "export CHIA_LOOPBACK_BIND_IP=127.200.0.1",
                              "export CHIA_LOOPBACK_PORT_MIN=23000",
                              "export CHIA_LOOPBACK_PORT_MAX=23099",
                              f"export LD_PRELOAD={runtime_host}/loopback-bind.so"],
        "head_start_ray_commands": [
            "python -m chia.cluster.loopback",
            "ray start --head --node-ip-address=127.200.0.1 --port=22379 --num-cpus=4 "
            "--include-dashboard=True --dashboard-host=127.0.0.1 --dashboard-port=22865 "
            "--ray-client-server-port=22380 --object-store-memory=268435456 --memory=2147483648 "
            "--node-manager-port=22900 --object-manager-port=22901 "
            "--min-worker-port=23000 --max-worker-port=23099 --dashboard-agent-listen-port=0 "
            "--temp-dir=/tmp/chia-research-head --disable-usage-stats"],
        "worker_start_ray_commands": [
            "python -m chia.cluster.loopback",
            "ray start --address=$RAY_HEAD_IP:22379 --node-ip-address=$CHIA_LOOPBACK_BIND_IP "
            "--num-cpus=4 --object-store-memory=1073741824 --memory=8589934592 "
            "--dashboard-agent-listen-port=0 --disable-usage-stats"],
    }


def validate_spec_install(spec_dir: Path, year: int) -> None:
    """Require an owned, writable installation of the selected licensed suite."""
    markers = ["shrc", "benchspec/CPU2006"] if year == 2006 else [
        "shrc", "bin/runcpu", "benchspec/CPU/605.mcf_s", "benchspec/CPU/648.exchange2_s"]
    if (not spec_dir.is_dir() or spec_dir.stat().st_uid != os.getuid() or
            not os.access(spec_dir, os.W_OK) or
            any(not (spec_dir / marker).exists() for marker in markers)):
        raise ValueError(f"SPEC{year} requires your owned writable installation with " + ", ".join(markers))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True, help="Your owned writable SPEC installation")
    parser.add_argument("--spec-year", type=int, choices=(2006, 2017), default=2006)
    parser.add_argument("--f2-ip", help="Optional public IP of the existing F2")
    parser.add_argument("--ssh-loopback-relay-ready", type=Path,
                        help="F2 readiness file for owned alias relays under GatewayPorts=no")
    parser.add_argument("--output", type=Path, default=Path("/scratch/chia-research/run"))
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/chia_research_aws.pem")
    parser.add_argument("--images-json", type=Path,
                        help="Imported image IDs from the daemon-free cache (FireSim is on F2)")
    args = parser.parse_args()
    spec_dir, output, key = args.spec_dir.resolve(), args.output.resolve(), args.ssh_key.expanduser().resolve()
    if args.f2_ip:
        try:
            ipaddress.IPv4Address(args.f2_ip)
        except ValueError:
            parser.error("--f2-ip must be an IPv4 address")
        if not key.is_file():
            parser.error(f"SSH key does not exist: {key}")
    try:
        validate_spec_install(spec_dir, args.spec_year)
    except ValueError as exc:
        parser.error(str(exc))
    import ray
    if sys.version_info[:3] != (3, 10, 19) or ray.__version__ != "2.54.0":
        parser.error("run this using the Chia Python 3.10.19 / Ray 2.54.0 environment")
    token = Path.home() / ".config/chia-research/ray.token"
    for path in [spec_dir, output, token, key, Path(sys.executable).absolute()]:
        if not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(path)):
            parser.error("paths must be absolute and contain only letters, digits, '/', '_', '.', '+', or '-'")
    token.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token.parent.chmod(0o700)
    if not token.exists():
        with token.open("x") as f:
            os.chmod(token, 0o600)
            f.write(secrets.token_hex(32) + "\n")
    token.chmod(0o600)
    if not token.read_text().strip():
        parser.error("the Ray token file is empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "fm-images").mkdir(exist_ok=True)
    # Docker's root daemon cannot traverse a private root-squashed NFS home.
    # Keep the canonical token there, and bind an equally private local copy.
    local_token = output / "ray.token"
    fd = os.open(local_token, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(token.read_text())
    token = local_token
    # The published image's /home/ray is 0750, group users (100). Keep the
    # host UID for owned SPEC files, allow toolchain traversal via that group,
    # and supply a private writable home for Git/compiler caches.
    (output / "compiler-home").mkdir(exist_ok=True, mode=0o700)
    (output / "compiler-builds").mkdir(exist_ok=True, mode=0o700)
    subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL)
    if args.images_json:
        images = cached_images(args.images_json)
    else:
        images = {name: pin_image(image) for name, image in IMAGES.items()}
        # Stage the image by this local ID; staging records F2's imported ID,
        # which can differ when the Docker image stores differ.
        images["firesim"] = _run(["docker", "image", "inspect", "--format", "{{.Id}}", images["firesim"]])
    # Build against the pinned container's libc, which also works on the lab host.
    # Compiling on a newer host can introduce unavailable GLIBC_2.38 symbols.
    runtime = output / "runtime"
    runtime.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "loopback_cluster" / "loopback_bind.c"
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--pull", "never",
                    "--user", f"{os.getuid()}:{os.getgid()}", "--group-add", "100",
                    "-v", f"{source}:/build/source.c:ro", "-v", f"{runtime}:/build/output",
                    "--entrypoint", "/usr/bin/gcc", images["riscv_build"],
                    "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-Wl,-z,relro,-z,now", "-o", "/build/output/loopback-bind.so",
                    "/build/source.c", "-ldl", "-pthread"], check=True)
    config = make_config(spec_dir, output, token, images, Path(sys.executable).absolute(), args.f2_ip, key,
                         args.spec_year, args.ssh_loopback_relay_ready)
    cluster = output / "cluster.yaml"
    cluster.write_text(json.dumps(config, indent=2) + "\n")
    (output / "images.json").write_text(json.dumps(images, indent=2) + "\n")
    env = output / "env.sh"
    env.write_text(f"export PATH={shlex.quote(str(Path(sys.executable).absolute().parent))}:$HOME/.local/bin:$PATH\n"
                   f"export SPEC_DIR_{args.spec_year}={shlex.quote(str(spec_dir))}\n"
                   f"export SPEC_DIR={shlex.quote(str(spec_dir))}\n"
                   "export RAY_AUTH_MODE=token\n"
                   "unset RAY_AUTH_TOKEN\n"
                   f"export RAY_AUTH_TOKEN_PATH={shlex.quote(str(token))}\n"
                   f"export LD_PRELOAD={shlex.quote(str(runtime / 'loopback-bind.so'))}\n"
                   "export CHIA_LOOPBACK_BIND_IP=127.200.0.1\n"
                   "export CHIA_LOOPBACK_PORT_MIN=23000\nexport CHIA_LOOPBACK_PORT_MAX=23099\n"
                   "export RAY_ADDRESS=127.200.0.1:22379\n")
    print(f"Prepared {cluster}")
    print(f"Shell environment: {env}")
    print("No AWS instances were launched and Ray has not been started.")
    if args.f2_ip:
        print("Before chia up: install Docker, load the pinned firesim image, and copy the token to the F2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
