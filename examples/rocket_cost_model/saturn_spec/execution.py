"""Guards for the reused native adapter. Preparation never enters this context."""

from contextlib import contextmanager
import json
from pathlib import Path
import shlex
import subprocess
import time

from .bundle import AGFI, DRIVER_SHA, read_json, sha
from .platform import REMOTE_CHECK, SDK, verify_platform
from .staging import verify_stage


def ssh_args(site):
    return ['ssh', '-i', site['ssh_key'], '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + site['known_hosts'], '-o', 'ConnectTimeout=15',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', 'ubuntu@' + site['worker_ip']]


@contextmanager
def guard(directory, task):
    """Refuse stale images/preflight, then hold the worker lease for one task.

    Only an operator resuming after bundle delivery may invoke a staged adapter.
    There is no hardware dispatcher in the preparation CLI.
    """
    if task not in ('infrasetup', 'runworkload'):
        raise ValueError('unsupported native manager task')
    out = Path(directory)
    plan = verify_stage(out)
    site = verify_platform(plan['platform'])
    image = read_json(out / 'image-receipt.json')
    preflight = read_json(out / 'preflight.json')
    if image.get('image_id') != plan['image_id'] or image.get('plan_sha256') != sha(out / 'plan.json') \
            or image.get('runtime_sha256') != plan['runtime_sha256']:
        raise ValueError('stale image receipt')
    for field in ('rootfs', 'bootbinary'):
        if sha(image[field]) != image[field + '_sha256']:
            raise ValueError('image artifact changed')
    if preflight.get('platform_sha256') != plan['identity']['platform_sha256'] \
            or not 0 <= time.time() - preflight.get('checked_at', 0) <= 300:
        raise ValueError('fresh preflight required immediately before each native task')
    # Require marshal's installed descriptor to point to these exact admitted bytes.
    workdir = Path(site['chipyard_root']) / 'sims/firesim/deploy/workloads'
    workload = read_json(workdir / (plan['name'] + '.json'))
    if workload.get('benchmark_name') != plan['name'] or workload.get('workloads'):
        raise ValueError('expected the single admitted workload')
    for key, field in [('common_rootfs', 'rootfs'), ('common_bootbinary', 'bootbinary')]:
        source = (workdir / plan['name'] / workload[key]).resolve()
        if source != Path(image[field]).resolve() or sha(source) != image[field + '_sha256']:
            raise ValueError('installed workload refers to a stale image')
    if task == 'runworkload' and read_json(out / 'infrasetup-completion.json').get('returncode') != 0:
        raise ValueError('successful same-stage infrastructure setup required')
    if (out / (task + '.started.json')).exists():
        raise ValueError('native task already attempted; prepare a fresh stage')
    ssh = ssh_args(site)
    lease = subprocess.Popen(ssh + ["flock -n /home/ubuntu/rocket-runtime.lock -c 'echo SATURN_SPEC_LEASE; cat >/dev/null'"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if lease.stdout.readline().strip() != 'SATURN_SPEC_LEASE':
            raise RuntimeError('worker is reserved by another controller')
        expected = {'sdk': SDK, 'instance': site['worker_id'], 'agfi': AGFI, 'driver': DRIVER_SHA,
                    'required_free_bytes': 1024**3 + (2 * Path(image['rootfs']).stat().st_size if task == 'infrasetup' else 0)}
        if task == 'runworkload':
            expected['images'] = {plan['name'] + '0-' + Path(image[k]).name: image[k + '_sha256']
                                  for k in ('rootfs', 'bootbinary')}
        subprocess.run(ssh + ['python3 - ' + shlex.quote(json.dumps(expected))], input=REMOTE_CHECK,
                       text=True, capture_output=True, check=True, timeout=120)
        started = time.time()
        if started > preflight['checked_at'] + 300:
            raise ValueError('preflight expired during image checks')
        record = {'backend': 'fpga', 'task': task, 'image_id': plan['image_id'],
                  'worker_id': site['worker_id'], 'worker_lease_held': True,
                  'agfi': AGFI, 'driver_sha256': DRIVER_SHA, 'vlen_bits': 256,
                  'phase': plan['identity']['phase'], 'sample': plan['identity']['sample'],
                  'started_at': started, 'plan_sha256': sha(out / 'plan.json'),
                  'image_receipt_sha256': sha(out / 'image-receipt.json'),
                  'preflight_sha256': sha(out / 'preflight.json')}
        with (out / (task + '.started.json')).open('x') as stream:
            stream.write(json.dumps(record, indent=2) + '\n')
        rc = 0
        try:
            yield
        except BaseException as exc:
            rc = (exc.code or 0) if isinstance(exc, SystemExit) and isinstance(exc.code, (int, type(None))) else 1
            raise
        finally:
            if lease.poll() is not None:
                rc = 1  # losing the lease invalidates a nominally successful manager run
            record.update(returncode=rc, finished_at=time.time())
            with (out / (task + '-completion.json')).open('x') as stream:
                stream.write(json.dumps(record, indent=2) + '\n')
    finally:
        if lease.stdin:
            lease.stdin.close()
        try:
            lease.wait(timeout=30)
        except subprocess.TimeoutExpired:
            lease.terminate()
            lease.wait(timeout=10)
