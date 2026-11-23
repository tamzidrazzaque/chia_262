"""Replay preserved guest bytes for boot diagnosis; never collect performance."""

import argparse
import copy
import json
from pathlib import Path
import shlex
import subprocess
import time
import uuid

import yaml

from examples.rocket_cost_model.saturn_spec.bundle import read_json, sha
from examples.rocket_cost_model.saturn_spec.execution import guard, ssh_args
from examples.rocket_cost_model.saturn_spec.platform import preflight, verify_platform
from examples.rocket_cost_model.saturn_spec.staging import verify_stage
from examples.rocket_cost_model.saturn_manager_contract import install_descriptor


def diagnostic_runtime(original, start_pc, end_pc, suffix, trace=True):
    """Change tracing and the diagnostic cycle bound, preserving target settings."""
    result = copy.deepcopy(original)
    if trace:
        result['tracing'] = {'enable': True, 'output_format': 0, 'selector': 2,
                             'start': hex(start_pc), 'end': hex(end_pc)}
    # Includes firmware time before Linux's uptime clock starts. This run only
    # diagnoses boot and cannot finish a normal SPEC timing sample.
    result['target_config']['plusarg_passthrough'] = '+max-cycles=6000000000'
    result['workload']['suffix_tag'] = suffix
    return result


def replay(stage, out, start_pc, end_pc, trace=True):
    """Use the accepted native adapter and full execution guard with a fresh audit."""
    stage, out = Path(stage).resolve(), Path(out).resolve()
    plan = verify_stage(stage)
    site = verify_platform(plan['platform'])
    image = read_json(stage / 'image-receipt.json')
    for field in ('rootfs', 'bootbinary'):
        if sha(image[field]) != image[field + '_sha256']:
            raise ValueError('preserved diagnostic image changed')
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    original = yaml.safe_load((stage / 'config_runtime.yaml').read_text())
    runtime = out / 'config_runtime.yaml'
    runtime.write_text(yaml.safe_dump(diagnostic_runtime(original, start_pc, end_pc,
        'boot-diagnostic-' + uuid.uuid4().hex[:12], trace), sort_keys=False))
    # Preserve the hardware-tested adapter; project only private config paths.
    adapter = Path(site['artifacts']['native_manager_adapter']['path']).read_text()
    replacements = {
        "'config_runtime_saturn_gate.yaml'": repr(str(runtime)),
        "'config_hwdb.yaml'": repr(str(stage / 'config_hwdb.yaml')),
        "system_known_hosts='/home/ubuntu/.ssh/known_hosts'":
            'system_known_hosts=' + repr(site['known_hosts'])}
    for source, target in replacements.items():
        if adapter.count(source) != 1:
            raise ValueError('accepted adapter projection changed')
        adapter = adapter.replace(source, target)
    native = out / 'native-diagnostic.py'; native.write_text(adapter)
    install_descriptor(stage, Path(site['chipyard_root']) / 'sims/firesim/deploy')
    provenance = {'diagnostic_only': True, 'source_stage': str(stage),
        'source_plan_sha256': sha(stage / 'plan.json'), 'rootfs_sha256': image['rootfs_sha256'],
        'bootbinary_sha256': image['bootbinary_sha256'], 'runtime_sha256': sha(runtime),
        'adapter_sha256': sha(native), 'tracing_enabled': trace,
        'trace_start_pc': hex(start_pc), 'trace_end_pc': hex(end_pc)}
    (out / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    codes = {}
    started = time.time()
    for task in ('infrasetup', 'runworkload'):
        (out / 'preflight.json').write_text(json.dumps(preflight(plan['platform']), indent=2) + '\n')
        try:
            with guard(stage, task, diagnostic_audit=out, diagnostic_runtime=runtime):
                with (out / (task + '.log')).open('w') as log:
                    command = [str(Path(site['chipyard_root']) / '.conda-env/bin/python'), str(native), task]
                    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            codes[task] = exc.returncode
            if task == 'infrasetup':
                raise
        else:
            codes[task] = 0
        if task == 'infrasetup':
            (out / 'preflight.json').rename(out / 'infrasetup-preflight.json')
    # Read private worker logs directly; do not change the installed workload
    # descriptor's output contract or copy a trace into Git.
    archive_script = ("import sys,tarfile; from pathlib import Path; "
        "root=Path('/home/ubuntu/sim_slot_0'); "
        "files=[root/'uartlog']+[p for p in root.glob('TRACEFILE*') "
        "if p.is_file() and not p.is_symlink() and p.stat().st_mtime >= " + str(started - 5) + "]; "
        "out=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
        "[(out.add(p,arcname=p.name,recursive=False)) for p in files]; out.close()")
    remote = 'python3 -c ' + shlex.quote(archive_script)
    with (out / 'worker-evidence.tar').open('wb') as archive:
        subprocess.run(ssh_args(site) + [remote], check=True, stdout=archive)
    import tarfile
    with tarfile.open(out / 'worker-evidence.tar') as archive:
        uart = archive.extractfile('uartlog').read()
        trace_names = [member.name for member in archive.getmembers() if member.name.startswith('TRACEFILE')]
    state = ('kernel_panic' if b'Kernel panic' in uart else
             'booted_to_workload' if b'launching firemarshal workload' in uart else 'no_boot_conclusion')
    result = {**provenance, 'status': state, 'manager_returncodes': codes,
              'trace_files': trace_names, 'evidence_sha256': sha(out / 'worker-evidence.tar')}
    (out / 'diagnosis.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--trace-start-pc', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--trace-end-pc', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--no-trace', action='store_true', help='untraced control using identical image bytes')
    args = parser.parse_args()
    print(json.dumps(replay(args.stage, args.out, args.trace_start_pc, args.trace_end_pc, not args.no_trace), indent=2))


if __name__ == '__main__':
    main()
