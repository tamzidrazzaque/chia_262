"""Compose a real-zstd FireMarshal Linux job inside a prepared build worker.

This command builds/composes disk images only. It never allocates instances or
programs an FPGA. Run in a worker with FireMarshal, loop mounts and the pinned
RISC-V environment; prepare_zstd_image creates its input directory.
"""

import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--image-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--firemarshal-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    if not 60 <= args.timeout <= 14400:
        parser.error("timeout must be 60..14400 seconds")
    description = json.loads((args.prepared / "workload.json").read_text())
    if not re.fullmatch(r"rocket-zstd-[0-9a-f]{16}", description["name"]):
        parser.error("invalid prepared workload identity")
    args.output.mkdir(parents=True, exist_ok=False)
    from chia.chipyard.firemarshal_node import FireMarshalNode
    node = FireMarshalNode(firemarshal_dir=str(args.firemarshal_dir.resolve()),
                          image_store=str(args.image_store.resolve()), timeout_seconds=args.timeout)
    fragment = args.firemarshal_dir.resolve() / "rocket-zstd-tools.brfrag"
    fragment.write_text("BR2_PACKAGE_BASH=y\nBR2_PACKAGE_COREUTILS=y\n")
    base_name = "rocket-zstd-base-bash-coreutils-v1"
    base = node.build_base(base_name, options={"base": "br-base.json",
        "distro": {"name": "br", "opts": {"configs": [str(fragment)]}}})
    (args.output / "base.stdout").write_text(base.stdout)
    (args.output / "base.stderr").write_text(base.stderr)
    if not base.success:
        raise RuntimeError("Linux base build failed; see saved diagnostics")
    root = args.prepared / "overlay"
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    expected = description["identity"]
    import hashlib
    for name, key in [("zstd", "binary_sha256"), ("input.tar", "input_sha256"), ("run.sh", "runner_sha256")]:
        if hashlib.sha256(files["root/zstd-pilot/" + name]).hexdigest() != expected[key]:
            raise ValueError("prepared overlay changed")
    def file_hash(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    base_dir = args.image_store.resolve() / base_name
    identity = {**expected,
        "linux_base_image_sha256": file_hash(base_dir / (base_name + ".img")),
        "bootbinary_sha256": file_hash(base_dir / (base_name + "-bin")),
        "distro_fragment_sha256": file_hash(fragment)}
    image_name = "rocket-zstd-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    files["root/zstd-pilot/identity.json"] = (json.dumps(identity, indent=2) + "\n").encode()
    result = node.compose(base_name, files, image_name,
                          config=description["config"], overlay_modes=description["modes"])
    (args.output / "compose.stdout").write_text(result.stdout)
    (args.output / "compose.stderr").write_text(result.stderr)
    if not result.success:
        raise RuntimeError("zstd image composition failed; see saved diagnostics")
    (args.output / "workload.tar.gz").write_bytes(result.archive)
    (args.output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (args.output / "descriptor.txt").write_text(result.json_name + "\n")
    print(args.output / "workload.tar.gz")


if __name__ == "__main__":
    main()
