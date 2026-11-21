"""Private Saturn-manager measure hook.

The hook intentionally requires explicit SSH/platform environment variables and
uses the admitted manager lane for image construction, F2 dispatch, and
collection.  It writes only the sanitized collection receipt locally.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"missing {name}")
    return value


def ssh(host: str, key: str, command: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["ssh", "-T", "-i", key, "-o", "StrictHostKeyChecking=yes", host,
         "bash --noprofile --norc -c " + shlex.quote(command)],
        check=True, text=True, capture_output=capture,
    )
    return result.stdout if capture else ""


def main() -> None:
    work = Path(env("SATURN_WORKDIR")).resolve()
    candidate = env("SATURN_CANDIDATE_ID")
    bundle = work / "bundle"
    manifest_sha = hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
    host, key = env("SATURN_MANAGER_HOST"), env("SATURN_MANAGER_KEY")
    root = env("SATURN_MANAGER_ROOT", "/home/ubuntu/cs262_compiler")
    lane = f"{root}/saturn-spec-lane"
    tag = "auto-" + candidate.replace(".", "-")
    incoming = f"{lane}/incoming/{tag}"
    verified = f"{lane}/verified/{tag}"
    stage = f"{lane}/staging/{tag}"
    local_tar = work / "bundle.tar"
    with tarfile.open(local_tar, "w") as archive:
        archive.add(bundle, arcname="bundle")
    remote_tar = f"{incoming}/bundle.tar"
    ssh(host, key, f"mkdir -p -m 700 {shlex.quote(incoming)} {shlex.quote(verified)} {shlex.quote(stage)}")
    with local_tar.open("rb") as source:
        sender = subprocess.Popen(["ssh", "-T", "-i", key, "-o", "StrictHostKeyChecking=yes", host,
                                   f"bash --noprofile --norc -c {shlex.quote(f'cat > {remote_tar}')}"], stdin=source)
        if sender.wait():
            raise RuntimeError("bundle transfer failed")
    remote = f"""
set -e
cd {shlex.quote(root)}
export PYTHONPATH={shlex.quote(root + '/chia_262-saturn')}
PY={shlex.quote(root + '/.venv/bin/python')}
tar -xf {shlex.quote(remote_tar)} -C {shlex.quote(incoming)}
$PY -m examples.rocket_cost_model.saturn_spec intake --bundle {shlex.quote(incoming + '/bundle')} --manifest-sha256 {manifest_sha} --verified-root {shlex.quote(verified)} --platform {shlex.quote(lane + '/platform-lock.json')}
SNAP={shlex.quote(verified + '/' + manifest_sha)}
$PY -m examples.rocket_cost_model.saturn_spec stage --snapshot "$SNAP" --platform {shlex.quote(lane + '/platform-lock.json')} --out {shlex.quote(stage)} --phase search --sample 0 --scratch-mib 1024
cd {shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal')}
export PATH={shlex.quote(root + '/chipyard-saturn-19a07f6/.conda-env/bin')}:$PATH
python {shlex.quote(lane + '/guarded-marshal.py')} build -I {shlex.quote(stage + '/workload.json')}
python {shlex.quote(lane + '/guarded-marshal.py')} install {shlex.quote(stage + '/workload.json')}
IMG=$(find {shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal/images/firechip')} -maxdepth 2 -type f -name '*.img' -printf '%T@ %p\\n' | sort -n | tail -n1 | cut -d' ' -f2-)
cd {shlex.quote(root)}
$PY -m examples.rocket_cost_model.saturn_spec verify-image --stage {shlex.quote(stage)} --rootfs "$IMG" --bootbinary {shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal/images/firechip/br-base/br-base-bin')} --out {shlex.quote(stage + '/image-receipt.json')}
cd {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim')}
source sourceme-manager.sh --skip-ssh-setup
$PY -m examples.rocket_cost_model.saturn_spec preflight --platform {shlex.quote(lane + '/platform-lock.json')} --out {shlex.quote(stage + '/preflight.json')}
python {shlex.quote(stage + '/native-manager-staged.py')} infrasetup
python {shlex.quote(stage + '/native-manager-staged.py')} runworkload
R=$(find {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim/deploy/results-workload')} -mindepth 1 -maxdepth 1 -type d -name '20*' -printf '%T@ %p\\n' | sort -n | tail -n1 | cut -d' ' -f2-)
COL=$(find "$R" -mindepth 1 -maxdepth 1 -type d | head -n1)
$PY -m examples.rocket_cost_model.saturn_spec collect --stage {shlex.quote(stage)} --image {shlex.quote(stage + '/image-receipt.json')} --completion {shlex.quote(stage + '/runworkload-completion.json')} --preflight {shlex.quote(stage + '/preflight.json')} --collected "$COL" --out {shlex.quote(stage + '/candidate-receipt.json')}
cat {shlex.quote(stage + '/candidate-receipt.json')}
"""
    receipt = ssh(host, key, remote, capture=True)
    start = receipt.find("{\n")
    if start < 0:
        raise RuntimeError("manager did not return a collection receipt")
    (work / "candidate-receipt.json").write_text(receipt[start:])


if __name__ == "__main__":
    main()
