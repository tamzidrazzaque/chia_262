"""Prepare a zstd Linux overlay and FireMarshal job without SPEC or FPGA access."""

import argparse
import hashlib
import json
from pathlib import Path


def overlay(pilot: Path, compiler: str = "rocket", inputs: str = "train"):
    """Read verified build bytes and create one isolated real-application job."""
    if compiler not in ("rocket", "native") or inputs not in ("train", "holdout"):
        raise ValueError("unknown compiler/input set")
    manifest = json.loads((pilot / "manifest.json").read_text())
    build = manifest["builds"][compiler]
    binary = Path(build["binary"]).read_bytes()
    corpus = (pilot / "corpora" / (inputs + ".tar")).read_bytes()
    if hashlib.sha256(binary).hexdigest() != build["sha256"] or hashlib.sha256(corpus).hexdigest() != manifest["corpora"][inputs]["sha256"]:
        raise ValueError("prepared application bytes changed")
    runner = Path(__file__).with_name("run_zstd.sh").read_bytes()
    identity = {"application": "zstd", "source_revision": manifest["source_revision"],
                "binary_sha256": build["sha256"], "input_sha256": manifest["corpora"][inputs]["sha256"],
                "input_set": inputs, "runner_sha256": hashlib.sha256(runner).hexdigest(),
                "flags": build["flags"], "compression_level": 3, "threads": 1}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = "root/zstd-pilot/"
    files = {root + "zstd": binary, root + "input.tar": corpus, root + "run.sh": runner,
             root + "identity.json": (json.dumps(identity, indent=2) + "\n").encode()}
    # The subshell runner may fail; collection status is still written and the
    # parent FireMarshal startup script proceeds to its unconditional shutdown.
    command = ("mkdir -p /output; cp /root/zstd-pilot/identity.json /output/identity.json; "
               "bash /root/zstd-pilot/run.sh /root/zstd-pilot/zstd /root/zstd-pilot/input.tar /output; "
               "rc=$?; echo $rc > /output/collection.status")
    config = {"jobs": [{"name": "zstd", "command": command, "outputs": ["/output"]}]}
    return {"name": "rocket-zstd-" + key[:16], "identity": identity, "files": files,
            "modes": {root + "zstd": 0o755, root + "run.sh": 0o755}, "config": config}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", choices=("train", "holdout"), default="train")
    args = parser.parse_args()
    prepared = overlay(args.pilot.resolve(), inputs=args.inputs)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in prepared.pop("files").items():
        path = args.output / "overlay" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(prepared["modes"].get(name, 0o644))
    (args.output / "workload.json").write_text(json.dumps(prepared, indent=2) + "\n")
    print(args.output / "workload.json")


if __name__ == "__main__":
    main()
