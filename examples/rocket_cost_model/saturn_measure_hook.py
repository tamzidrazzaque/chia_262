"""Private Saturn-manager measure hook.

The hook intentionally requires explicit SSH/platform environment variables and
uses the admitted manager lane for image construction, F2 dispatch, and
collection.  It writes only the sanitized collection receipt locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import uuid


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"missing {name}")
    return value


def ssh(host: str, key: str, command: str, capture: bool = False) -> str:
    if os.environ.get('SATURN_MANAGER_LOCAL') == '1':
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c', command],
                                check=True, text=True, capture_output=capture)
        return result.stdout if capture else ''
    result = subprocess.run(
        ["ssh", "-T", "-i", key, "-o", "StrictHostKeyChecking=yes", host,
         "bash --noprofile --norc -c " + shlex.quote(command)],
        check=True, text=True, capture_output=capture,
    )
    return result.stdout if capture else ""


def main() -> None:
    work = Path(env("SATURN_WORKDIR")).resolve()
    candidate = env("SATURN_CANDIDATE_ID")
    if not re.fullmatch(r"3\.[0-9]+", candidate):
        raise ValueError("invalid queue candidate ID")
    # The producer keeps role-specific payloads below ``bundle/<role>`` so a
    # single candidate work directory can hold more than one role.  The
    # search lane measures the Saturn-aware role-3 payload.
    role = os.environ.get('SATURN_ROLE', '3-saturn-aware')
    if role not in ('1-scalar', '2-generic-vector', '3-saturn-aware'):
        raise ValueError('unsupported measurement role')
    bundle = work / "bundle" / role
    manifest_sha = hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
    local = os.environ.get('SATURN_MANAGER_LOCAL') == '1'
    host, key = ('local', '') if local else (env("SATURN_MANAGER_HOST"), env("SATURN_MANAGER_KEY"))
    root = env("SATURN_MANAGER_ROOT", "/home/ubuntu/cs262_compiler")
    lane = env('SATURN_MANAGER_LANE', f"{root}/saturn-spec-lane")
    tag = "auto-" + candidate.replace(".", "-")
    incoming = f"{lane}/incoming/{tag}"
    verified = f"{lane}/verified/{tag}"
    stage = f"{lane}/staging/{tag}"
    phase = os.environ.get('SATURN_PHASE', 'search')
    sample = os.environ.get('SATURN_SAMPLE', '0')
    if phase not in ('baseline', 'search', 'confirmation', 'holdout') or not sample.isdigit():
        raise ValueError('invalid paired measurement phase/sample')
    local_tar = work / "bundle.tar"
    with tarfile.open(local_tar, "w") as archive:
        archive.add(bundle, arcname="bundle")
    remote_tar = f"{incoming}/bundle.tar"
    ssh(host, key, f"test ! -e {shlex.quote(stage)} && mkdir -p -m 700 {shlex.quote(incoming)} {shlex.quote(verified)}")
    if local:
        shutil.copyfile(local_tar, remote_tar)
    else:
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
$PY -m examples.rocket_cost_model.saturn_spec stage --snapshot "$SNAP" --platform {shlex.quote(lane + '/platform-lock.json')} --out {shlex.quote(stage)} --phase {phase} --sample {sample} --scratch-mib 1024
source {shlex.quote(root + '/chipyard-saturn-19a07f6/env.sh')}
cd {shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal')}
export PATH={shlex.quote(root + '/chipyard-saturn-19a07f6/.conda-env/bin')}:$PATH
flock {shlex.quote(root + '/saturn-firemarshal.lock')} python {shlex.quote(lane + '/guarded-marshal.py')} build -I {shlex.quote(stage + '/workload.json')}
flock {shlex.quote(root + '/saturn-firemarshal.lock')} python {shlex.quote(lane + '/guarded-marshal.py')} install {shlex.quote(stage + '/workload.json')}
NAME=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' {shlex.quote(stage + '/plan.json')})
IMG={shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal/images/firechip')}/$NAME/$NAME.img
test -f "$IMG"
cd {shlex.quote(root)}
$PY -m examples.rocket_cost_model.saturn_spec verify-image --stage {shlex.quote(stage)} --rootfs "$IMG" --bootbinary {shlex.quote(root + '/chipyard-saturn-19a07f6/software/firemarshal/images/firechip/br-base/br-base-bin')} --out {shlex.quote(stage + '/image-receipt.json')}
$PY -m examples.rocket_cost_model.saturn_manager_contract install-descriptor --stage {shlex.quote(stage)} --deploy {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim/deploy')}
cd {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim')}
source sourceme-manager.sh --skip-ssh-setup
$PY -m examples.rocket_cost_model.saturn_spec preflight --platform {shlex.quote(lane + '/platform-lock.json')} --out {shlex.quote(stage + '/preflight.json')}
python {shlex.quote(stage + '/native-manager-staged.py')} infrasetup
# Each task requires its own fresh preflight. Preserve the infrastructure check.
mv {shlex.quote(stage + '/preflight.json')} {shlex.quote(stage + '/infrasetup-preflight.json')}
$PY -m examples.rocket_cost_model.saturn_spec preflight --platform {shlex.quote(lane + '/platform-lock.json')} --out {shlex.quote(stage + '/preflight.json')}
python {shlex.quote(stage + '/native-manager-staged.py')} runworkload
COL=$($PY -c 'from pathlib import Path; import sys; hits=list(Path(sys.argv[1]).glob("*"+sys.argv[2]+"*/**/uartlog")); assert len(hits)==1, "ambiguous or missing run evidence"; print(hits[0].parent)' {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim/deploy/results-workload')} "$NAME")
$PY -m examples.rocket_cost_model.saturn_spec collect --stage {shlex.quote(stage)} --image {shlex.quote(stage + '/image-receipt.json')} --completion {shlex.quote(stage + '/runworkload-completion.json')} --preflight {shlex.quote(stage + '/preflight.json')} --collected "$COL" --out {shlex.quote(stage + '/collection')}
# Maintenance cannot discard an already valid measurement. Preserve any failure
# for diagnosis; the next worker preflight still enforces available capacity.
if ! $PY -m examples.rocket_cost_model.saturn_space --stage {shlex.quote(stage)} > {shlex.quote(stage + '/space-receipt.json')} 2> {shlex.quote(stage + '/space-maintenance.log')}; then
  printf 'Completed image maintenance failed; inspect space-maintenance.log\\n' >&2
fi
"""
    ssh(host, key, remote)
    marker = 'SATURN_RECEIPT_' + uuid.uuid4().hex
    output = ssh(host, key, "printf '%s\\n' " + shlex.quote(marker) + "; cat "
                 + shlex.quote(stage + '/collection/result.json'), capture=True)
    # Some manager login shells print ssh-agent banners. A per-call marker
    # delimits only the dedicated receipt transfer, never mixed manager logs.
    if output.count(marker + '\n') != 1:
        raise ValueError('missing or ambiguous receipt transfer marker')
    receipt = json.loads(output.split(marker + '\n', 1)[1])
    if receipt.get('identity', {}).get('bundle_sha256') != manifest_sha:
        raise ValueError('manager returned a different bundle receipt')
    (work / "candidate-receipt.json").write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == "__main__":
    main()
