"""Stage the FireSim image, matching SDK, and Ray token over SSH.

Requires an Ubuntu FPGA Developer AMI with Docker already usable by ubuntu.
Downloads happen on the lab host; this program changes no AWS network rules.
"""

import argparse
import hashlib
import ipaddress
import json
import re
import shlex
import subprocess
import tarfile
from pathlib import Path


def validate_image_archive(archive: Path, image: str) -> None:
    """Require a single-image Docker archive with the expected content ID."""
    with tarfile.open(archive) as contents:
        manifest = json.load(contents.extractfile("manifest.json"))
        if len(manifest) != 1:
            raise ValueError("the archive must contain exactly one image")
        config = contents.extractfile(manifest[0]["Config"]).read()
    if "sha256:" + hashlib.sha256(config).hexdigest() != image:
        raise ValueError("the archive does not match the pinned image content ID")


def loaded_image_id(output: str) -> str:
    """Read the immutable runtime ID returned by an untagged docker load."""
    ids = re.findall(r"^Loaded image ID: (sha256:[0-9a-f]{64})$", output, re.MULTILINE)
    if len(ids) != 1:
        raise ValueError("docker load did not return exactly one image ID")
    return ids[0]


def stage_sdk(ssh: list[str], image: str) -> None:
    """Copy the image's SDK on F2, refusing to replace a different host SDK."""
    # Keep FireSim's .git/modules alongside its submodule until the SDK clone
    # completes. Extracting only the submodule loses its Git metadata.
    script = """set -e
stage=$(mktemp -d /home/ubuntu/chia-setup/sdk-stage.XXXXXX)
container=''
cleanup() {
    if [ -n "$container" ]; then docker rm "$container" >/dev/null; fi
    rm -rf "$stage"
}
trap cleanup EXIT
container=$(docker create --pull never IMAGE)
docker cp "$container:/home/ray/firesim" "$stage/"
sdk="$stage/firesim/platforms/f2/aws-fpga-firesim-f2"
revision=$(git -C "$sdk" rev-parse HEAD)
if [ -e /home/ubuntu/aws-fpga ] || [ -L /home/ubuntu/aws-fpga ]; then
    if [ "$(git -C /home/ubuntu/aws-fpga rev-parse HEAD)" != "$revision" ]; then
        echo 'Existing host FPGA SDK revision differs; refusing to overwrite it.' >&2
        exit 1
    fi
else
    git clone --no-local "$sdk" /home/ubuntu/aws-fpga
fi
echo "FPGA SDK revision: $revision"
cd /home/ubuntu/aws-fpga
# Management tools build locally. Optional Cython bindings may be unavailable;
# pip must fail promptly instead of trying the offline host's blocked internet.
export PIP_NO_INDEX=1
source sdk_setup.sh
# FireSim sources SDK setup again during infrasetup. Keep that SDK virtualenv
# offline as well, including when its caller does not inherit this environment.
venv=sdk/userspace/cython_bindings/venv
if [ -d "$venv" ]; then
    printf '[global]\\nno-index = true\\ndisable-pip-version-check = true\\n' > "$venv/pip.conf"
fi
""".replace("IMAGE", shlex.quote(image))
    subprocess.run(ssh + ["bash -lc " + shlex.quote(script)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--f2-ip", required=True)
    parser.add_argument("--output", type=Path, default=Path("/scratch/chia-research/run"))
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/chia_research_aws.pem")
    parser.add_argument("--image-archive", type=Path,
                        help="Crane --format legacy archive; needs no local Docker daemon")
    args = parser.parse_args()
    ipaddress.IPv4Address(args.f2_ip)
    images_path = args.output / "images.json"
    images = json.loads(images_path.read_text())
    image = images["firesim"]
    config_id = images.get("firesim_archive_config_id", image)
    token = Path.home() / ".config/chia-research/ray.token"
    if not token.is_file() or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        parser.error("run prepare_cluster.py first")
    if args.image_archive:
        validate_image_archive(args.image_archive, config_id)
    target = "ubuntu@" + args.f2_ip
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
           "-o", "ConnectTimeout=15", "-i", str(args.ssh_key.expanduser()), target]
    subprocess.run(ssh + ["set -e; docker info >/dev/null; command -v git; command -v make; command -v gcc; "
                          "umask 077; mkdir -p /home/ubuntu/chia-setup"], check=True)
    subprocess.run(["scp", "-i", str(args.ssh_key.expanduser()), str(token),
                    target + ":/home/ubuntu/chia-setup/ray.token"], check=True)
    subprocess.run(ssh + ["chmod 600 /home/ubuntu/chia-setup/ray.token"], check=True)
    cached = subprocess.run(ssh + ["docker image inspect " + shlex.quote(image)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if cached.returncode:
        print("Loading the pinned FireSim image over SSH...", flush=True)
        if args.image_archive:
            with args.image_archive.open("rb") as archive:
                output = subprocess.check_output(ssh + ["docker load"], stdin=archive, text=True)
        else:
            with subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE) as saved:
                output = subprocess.check_output(ssh + ["docker load"], stdin=saved.stdout, text=True)
                saved.stdout.close()
                if saved.wait():
                    raise RuntimeError("docker save failed")
        image = loaded_image_id(output)
        # The containerd image store uses the imported manifest digest as
        # its runtime ID. Keep the archive config ID for validation/reuse.
        images["firesim_archive_config_id"] = config_id
        images["firesim"] = image
        images_path.write_text(json.dumps(images, indent=2) + "\n")
        cluster_path = args.output / "cluster.yaml"
        if cluster_path.exists():
            import yaml
            config = yaml.safe_load(cluster_path.read_text())
            node = config.get("available_node_types", {}).get("firesim")
            if node:
                node["docker"]["image"] = image
                cluster_path.write_text(json.dumps(config, indent=2) + "\n")
        print(output.strip(), flush=True)
    command = ("docker run --rm --network none --pull never --entrypoint python "
               + shlex.quote(image) + " -c " + shlex.quote(
                   "import sys,ray; print('.'.join(map(str,sys.version_info[:3])),ray.__version__)"))
    version = subprocess.check_output(ssh + [command], text=True).strip()
    if version != "3.10.19 2.54.0":
        raise RuntimeError(f"FireSim uses {version}; expected Python 3.10.19 and Ray 2.54.0")
    print("Staging the matching FPGA SDK...", flush=True)
    stage_sdk(ssh, image)
    print("F2 staged. Cluster startup still requires the lab host Docker access and self-SSH.")


if __name__ == "__main__":
    main()
