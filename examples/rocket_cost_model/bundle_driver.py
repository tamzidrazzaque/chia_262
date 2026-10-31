"""Collect a driver and generated build evidence from the pinned Rocket tree.

A source-derived bundle is not automatically approved for hardware execution.
The output manifest deliberately leaves matching_source_verified false until
its provenance/bridge interfaces are reviewed against the FPGA image.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from chia.chipyard import rocket_target as target


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chipyard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cy = args.chipyard.resolve()
    fs = cy / "sims/firesim"
    pins = {"Chipyard_revision": (cy, target.CHIPYARD), "FireSim_revision": (fs, target.FIRESIM),
            "Rocket_revision": (cy / "generators/rocket-chip", target.ROCKET)}
    for name, (path, revision) in pins.items():
        if git(path) != revision:
            raise ValueError("source pin differs: " + name)
    generated = fs / "sim/generated-src/f2" / target.QUINTUPLET
    driver = fs / "sim/output/f2" / target.QUINTUPLET / "FireSim-f2"
    headers = sorted(generated.glob("*.h"))
    if not driver.is_file() or not headers:
        raise ValueError("driver or generated bridge headers missing")
    args.output.mkdir(parents=True, exist_ok=False)
    stage = args.output / "driver"
    stage.mkdir()
    shutil.copy2(driver, stage / driver.name)
    ldd = subprocess.check_output(["ldd", str(driver)], text=True)
    if "not found" in ldd:
        raise ValueError("driver shared-library dependency missing")
    for line in ldd.splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.+-]+) => (/\S+)", line)
        if not match:
            continue
        name, path = match[1], Path(match[2]).resolve()
        if name in ("libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1"):
            continue
        # Bundle portable non-glibc libraries; retain all dependency paths in
        # private evidence so host-vs-container linkage can be checked.
        shutil.copy2(path, stage / name)
    bundle = args.output / "driver-bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for path in sorted(stage.iterdir()):
            archive.add(path, arcname=path.name, recursive=False)
    evidence = {name: revision for name, (_, revision) in pins.items()}
    evidence.update(quintuplet=target.QUINTUPLET, driver_sha256=sha(driver), ldd=ldd,
        SDK_revision=git(fs / "platforms/f2/aws-fpga-firesim-f2"),
        generated_files={str(p.relative_to(generated)): sha(p) for p in sorted(generated.iterdir()) if p.is_file()},
        bundle_files={p.name: sha(p) for p in stage.iterdir()},
        source_status={name: subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"], text=True)
                       for name, (path, _) in pins.items()},
        FPGA_executed=False)
    record = args.output / "build-evidence.json"
    record.write_text(json.dumps(evidence, indent=2) + "\n")
    manifest = {name: revision for name, (_, revision) in pins.items()}
    manifest.update(AGFI=target.AGFI, AFI=target.AFI, shell="0x10212415", quintuplet=target.QUINTUPLET,
        SDK_revision=evidence["SDK_revision"],
        driver_bundle=str(bundle.resolve()), driver_bundle_sha256=sha(bundle),
        build_evidence=str(record.resolve()), build_evidence_sha256=sha(record), matching_source_verified=False,
        note="Built from pinned source. Review FPGA-image provenance and generated interfaces before approval.")
    (args.output / "hardware.unverified.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.output / "hardware.unverified.json")


if __name__ == "__main__":
    main()
