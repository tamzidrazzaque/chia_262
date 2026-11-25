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


def retryable_early_boot_failure(uart_path: Path, result_path: Path) -> dict | None:
    """Recognize only the recorded pre-job interrupt panic, independent of RC.

    FireSim can return zero after the simulator exits cleanly even when Linux
    panicked before the workload created its result directory. Workload
    failures that created a result directory or emitted the guest exit marker
    are deliberately excluded.
    """
    if Path(result_path).exists():
        return None
    payload = Path(uart_path).read_bytes()
    text = payload.decode(errors='replace')
    if ('Kernel panic - not syncing: Fatal exception in interrupt' not in text or
            'SATURN_SPEC_JOB_EXIT=' in text):
        return None
    return {'classification': 'early_kernel_panic_before_guest_job',
            'uart_sha256': hashlib.sha256(payload).hexdigest()}


def retryable_failure_record(uart_path: Path, result_path: Path,
                             identity_path: Path) -> dict | None:
    """Bind the UART classification to the identity embedded in the image."""
    failure = retryable_early_boot_failure(uart_path, result_path)
    if failure is None:
        return None
    identity = json.loads(Path(identity_path).read_text())
    keys = ('worker_id', 'platform_sha256', 'bundle_sha256', 'input_id', 'role', 'sample', 'phase')
    if any(key not in identity for key in keys):
        raise ValueError('guest stage identity is incomplete for boot-failure receipt')
    return {**failure, 'identity': {key: identity[key] for key in keys}}


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
    phase = os.environ.get('SATURN_PHASE', 'search')
    sample = os.environ.get('SATURN_SAMPLE', '0')
    if phase not in ('baseline', 'search', 'confirmation', 'holdout') or not sample.isdigit():
        raise ValueError('invalid paired measurement phase/sample')
    deadline = os.environ.get('SATURN_RUN_MAX_SECONDS')
    watchdog_deadline_args = ''
    if deadline is not None:
        if not deadline.isdigit() or not 60 <= int(deadline) <= 3600:
            raise ValueError('SATURN_RUN_MAX_SECONDS must be 60..3600')
    # Keep every physical attempt in a distinct private stage. Failed stages
    # are preserved for diagnosis, so a candidate-only name would prevent a
    # retry (or a paired confirmation repeat) from reaching dispatch.
    attempt = uuid.uuid4().hex[:12]
    tag = f"auto-{candidate.replace('.', '-')}-{phase}-{sample}-{attempt}"
    incoming = f"{lane}/incoming/{tag}"
    verified = f"{lane}/verified/{tag}"
    stage = f"{lane}/staging/{tag}"
    if deadline is not None:
        watchdog_deadline_args = ('--diagnostic-seconds ' + deadline +
            ' --evidence-directory ' + shlex.quote(stage + '/guest-time-budget-evidence'))
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
if $PY -m examples.rocket_cost_model.saturn_run_watchdog --stage {shlex.quote(stage)} {watchdog_deadline_args} -- python {shlex.quote(stage + '/native-manager-staged.py')} runworkload; then
  RUN_RC=0
else
  RUN_RC=$?
fi
# Classify from the guest evidence regardless of FireSim's return code: an
# early Linux panic can still produce a clean simulator exit (returncode 0).
UART=$($PY -c 'from pathlib import Path; import sys; hits=list(Path(sys.argv[1]).glob("*"+sys.argv[2]+"*/**/uartlog")); assert len(hits)<=1, "ambiguous run evidence"; print(hits[0] if hits else "")' {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim/deploy/results-workload')} "$NAME")
if [ -n "$UART" ]; then
  $PY - {shlex.quote(stage + '/overlay/root/saturn-spec/stage-identity.json')} "$UART" "$(dirname "$UART")/result" {shlex.quote(stage + '/retryable-boot-failure.json')} <<'PYFAIL'
import json, sys
from pathlib import Path
from examples.rocket_cost_model.saturn_measure_hook import retryable_failure_record
record = retryable_failure_record(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[1]))
if record is None:
    sys.exit(0)
Path(sys.argv[4]).write_text(json.dumps(record, sort_keys=True) + '\\n')
sys.exit(75)
PYFAIL
fi
if [ "$RUN_RC" -ne 0 ]; then exit "$RUN_RC"; fi
COL=$($PY -c 'from pathlib import Path; import sys; hits=list(Path(sys.argv[1]).glob("*"+sys.argv[2]+"*/**/uartlog")); assert len(hits)==1, "ambiguous or missing run evidence"; print(hits[0].parent)' {shlex.quote(root + '/chipyard-saturn-19a07f6/sims/firesim/deploy/results-workload')} "$NAME")
$PY -m examples.rocket_cost_model.saturn_spec collect --stage {shlex.quote(stage)} --image {shlex.quote(stage + '/image-receipt.json')} --completion {shlex.quote(stage + '/runworkload-completion.json')} --preflight {shlex.quote(stage + '/preflight.json')} --collected "$COL" --out {shlex.quote(stage + '/collection')}
# Maintenance cannot discard an already valid measurement. Preserve any failure
# for diagnosis; the next worker preflight still enforces available capacity.
if ! $PY -m examples.rocket_cost_model.saturn_space --stage {shlex.quote(stage)} > {shlex.quote(stage + '/space-receipt.json')} 2> {shlex.quote(stage + '/space-maintenance.log')}; then
  printf 'Completed image maintenance failed; inspect space-maintenance.log\\n' >&2
fi
"""
    try:
        ssh(host, key, remote)
    except subprocess.CalledProcessError:
        marker = 'SATURN_RETRYABLE_BOOT_' + uuid.uuid4().hex
        output = ssh(host, key, "printf '%s\\n' " + shlex.quote(marker) + "; if test -f " +
                    shlex.quote(stage + '/retryable-boot-failure.json') + "; then cat " +
                    shlex.quote(stage + '/retryable-boot-failure.json') + "; else printf '{}'; fi",
                    capture=True)
        if output.count(marker + '\n') == 1:
            try:
                failure = json.loads(output.split(marker + '\n', 1)[1])
            except json.JSONDecodeError:
                failure = None
            expected = {'bundle_sha256': manifest_sha, 'role': role,
                        'sample': int(sample), 'phase': phase}
            identity = failure.get('identity', {}) if isinstance(failure, dict) else {}
            if failure and failure.get('classification') == 'early_kernel_panic_before_guest_job' and \
                    all(identity.get(key) == value for key, value in expected.items()):
                (work / 'candidate-retryable-boot-failure.json').write_text(
                    json.dumps(failure, indent=2) + '\n')
                return
        raise
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
