"""Prepare an image plan and overlay; never invoke marshal or a hardware run."""

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import uuid

import yaml

from .bundle import AGFI, DRIVER_SHA, canonical, digest, read_json, relative, regular_tree, sha, verify
from .platform import verify_platform


def files_hashes(root):
    return {name: sha(root / name) for name in sorted(regular_tree(root))}


def runner(m, identity):
    root = '/root/saturn-spec'
    lines = ['#!/bin/sh', 'set -eu', f'ROOT={root}', 'WORK="$ROOT/work"', 'RESULT="$ROOT/result"',
             'test ! -e "$RESULT"', 'mkdir -p "$WORK" "$RESULT/outputs"',
             "printf '%s\\n' " + shlex.quote(json.dumps(identity, sort_keys=True)) + ' > "$RESULT/identity.json"',
             'cat /proc/cpuinfo > "$RESULT/cpuinfo.txt"', 'uname -a > "$RESULT/uname.txt"',
             'sha256sum "$ROOT/rvv-probe" > "$RESULT/probe.sha256"',
             '"$ROOT/rvv-probe" > "$RESULT/probe.txt" 2>&1',
             'cp "$ROOT/bundle/' + m['executable'] + '" "$WORK/program"', 'chmod 500 "$WORK/program"']
    checks = [(m['executable'], 'program')]
    for dest, source in m['inputs'].items():
        lines += ['mkdir -p ' + shlex.quote(root + '/work/' + str(Path(dest).parent)),
                  'cp ' + shlex.quote(root + '/bundle/' + source) + ' ' + shlex.quote(root + '/work/' + dest)]
        checks.append((source, dest))
    for source, dest in checks:
        record = m['files_sha256'][source] + '  ' + root + '/work/' + dest
        lines += ["printf '%s\\n' " + shlex.quote(record) + ' | sha256sum -c - >/dev/null']
    for dest in {m['stdout'], m['stderr'], *m['expected_outputs']}:
        lines += ['mkdir -p ' + shlex.quote(root + '/work/' + str(Path(dest).parent)),
                  'mkdir -p ' + shlex.quote(root + '/result/outputs/' + str(Path(dest).parent))]
    lines += ['cd "$WORK"', 'sha256sum program > "$RESULT/executable.sha256"', 'set +e']
    stdin = shlex.quote(m['stdin']) if m['stdin'] is not None else '/dev/null'
    command = ['/bin/busybox', 'time', '-p', '-o', root + '/result/time.txt', *m['argv']]
    lines += [shlex.join(command) + ' < ' + stdin + ' > ' + shlex.quote(m['stdout']) + ' 2> ' + shlex.quote(m['stderr']),
              'status=$?', "printf '%s\\n' \"$status\" > \"$RESULT/job.status\"", 'collect=0']
    for dest in sorted({m['stdout'], m['stderr'], *m['expected_outputs']}):
        lines += ['cp ' + shlex.quote(root + '/work/' + dest) + ' ' + shlex.quote(root + '/result/outputs/' + dest) + ' || collect=1']
    lines += ["printf '%s\\n' \"$collect\" > \"$RESULT/collection.status\"",
              'printf "SATURN_SPEC_JOB_EXIT=%s COLLECTION=%s\\n" "$status" "$collect"', 'sync']
    return '\n'.join(lines) + '\n'


def stage(snapshot, platform_path, output, phase, sample, scratch_mib=1024):
    site = verify_platform(platform_path)
    snapshot = Path(snapshot)
    if (snapshot / 'REJECTED').exists():
        raise ValueError('rejected intake')
    receipt = read_json(snapshot / 'intake.json')
    bundle_id = digest(receipt['manifest_sha256'])
    if snapshot.name != bundle_id:
        raise ValueError('snapshot directory is not content-addressed by its manifest')
    m = verify(snapshot / 'bundle', bundle_id, site['readelf'], site['objdump'])
    if phase not in ('baseline', 'search', 'confirmation', 'holdout') or type(sample) is not int or sample < 0:
        raise ValueError('invalid phase/sample')
    if type(scratch_mib) is not int or not 0 <= scratch_mib <= 65536:
        raise ValueError('scratch MiB must be between 0 and 65536')
    bundle_root = snapshot / 'bundle'
    payload_bytes = sum((bundle_root / n).stat().st_size for n in m['files_sha256'])
    work_bytes = sum((bundle_root / n).stat().st_size for n in [m['executable'], *m['inputs'].values()])
    golden_bytes = sum((bundle_root / n).stat().st_size for n in m['expected_outputs'].values())
    required_bytes = (Path(site['artifacts']['base_rootfs']['path']).stat().st_size + payload_bytes
                      + work_bytes + 2 * golden_bytes + (scratch_mib + 64) * 1024**2)
    # Round to GiB so small ELF-size differences don't normally resize role images.
    rootfs_gib = max(2, (required_bytes + 1024**3 - 1) // 1024**3)
    identity = {'schema_version': 1, 'bundle_sha256': bundle_id, 'platform_sha256': sha(platform_path),
                'role': m['role'], 'benchmark': m['benchmark'], 'input_id': m['input_id'],
                'phase': phase, 'sample': sample, 'nonce': uuid.uuid4().hex,
                'worker_id': site['worker_id'], 'agfi': AGFI, 'driver_sha256': DRIVER_SHA,
                'vlen_bits': 256, 'protocol': 'busybox-time-posix-elapsed-v1',
                'rootfs_gib': rootfs_gib, 'scratch_mib': scratch_mib}
    # Runner bytes, base and platform identities are part of the stage identity.
    script = runner(m, identity)
    image_id = canonical({'identity': identity, 'runner_sha256': hashlib.sha256(script.encode()).hexdigest()})
    name = 'saturn-spec-' + image_id[:24]
    out = Path(output)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    overlay = out / 'overlay/root/saturn-spec'
    overlay.mkdir(parents=True)
    shutil.copytree(snapshot / 'bundle', overlay / 'bundle', symlinks=True)
    verify(overlay / 'bundle', bundle_id, site['readelf'], site['objdump'])
    shutil.copyfile(site['artifacts']['rvv_probe']['path'], overlay / 'rvv-probe')
    (overlay / 'rvv-probe').chmod(0o500)
    (overlay / 'run.sh').write_text(script)
    (overlay / 'stage-identity.json').write_text(json.dumps({'image_id': image_id, **identity}, sort_keys=True) + '\n')
    config = {'name': name, 'base': 'br-base.json', 'rootfs-size': str(rootfs_gib) + 'GiB', 'workdir': str(out.resolve()),
              'overlay': str((out / 'overlay').resolve()), 'command': 'sh /root/saturn-spec/run.sh',
              'outputs': ['/root/saturn-spec/result']}
    (out / 'workload.json').write_text(json.dumps(config, indent=2) + '\n')
    runtime = yaml.safe_load(Path(site['artifacts']['runtime_template']['path']).read_text())
    runtime['run_farm'] = {'base_recipe': 'run-farm-recipes/externally_provisioned.yaml',
                          'recipe_arg_overrides': {'run_farm_hosts_to_use': [{site['worker_ip']: 'one_fpga_spec'}]}}
    runtime['metasimulation']['metasimulation_enabled'] = False
    runtime['target_config'].update(topology='no_net_config', no_net_num_nodes=1,
        default_hw_config='firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3', plusarg_passthrough='')
    runtime['workload'].update(workload_name=name + '.json', terminate_on_completion=True, suffix_tag=image_id[:16])
    (out / 'config_runtime.yaml').write_text(yaml.safe_dump(runtime, sort_keys=False))
    hwdb = {'firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3': {
        'agfi': AGFI, 'driver_tar': Path(site['artifacts']['driver_bundle']['path']).as_uri(),
        'deploy_quintuplet_override': None,
        'deploy_makefrag_override': str(Path(site['chipyard_root']) / 'generators/firechip/chip/src/main/makefrag/firesim'),
        'custom_runtime_config': None}}
    (out / 'config_hwdb.yaml').write_text(yaml.safe_dump(hwdb, sort_keys=False))
    adapter = Path(site['artifacts']['native_manager_adapter']['path']).read_text()
    # Reuse the tested process-local SSH/SDK adapter, changing only config paths.
    for old, new in {
        "'config_runtime_saturn_gate.yaml'": repr(str((out / 'config_runtime.yaml').resolve())),
        "'config_hwdb.yaml'": repr(str((out / 'config_hwdb.yaml').resolve())),
    }.items():
        if adapter.count(old) != 1:
            raise ValueError('accepted native adapter layout changed')
        adapter = adapter.replace(old, new)
    prefix = ("import sys\nfrom examples.rocket_cost_model.saturn_spec.execution import guard\n"
              + "with guard(" + repr(str(out.resolve())) + ", sys.argv[1]):\n"
              + "    exec(compile(" + repr(adapter) + ", __file__, 'exec'), globals())\n")
    (out / 'native-manager-staged.py').write_text(prefix)
    plan = {'schema_version': 1, 'image_id': image_id, 'identity': identity, 'name': name,
            'overlay_sha256': files_hashes(out / 'overlay'), 'workload_sha256': sha(out / 'workload.json'),
            'runtime_sha256': sha(out / 'config_runtime.yaml'),
            'hwdb_sha256': sha(out / 'config_hwdb.yaml'),
            'adapter_sha256': sha(out / 'native-manager-staged.py'), 'snapshot': str(snapshot.resolve()),
            'platform': str(Path(platform_path).resolve()), 'state': 'staged_only_not_constructed',
            'expected_bootbinary_sha256': site['artifacts']['base_bootbinary']['sha256']}
    (out / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return plan


def verify_stage(directory):
    out = Path(directory)
    p = read_json(out / 'plan.json')
    site = verify_platform(p['platform'])
    if sha(p['platform']) != p['identity']['platform_sha256'] \
            or files_hashes(out / 'overlay') != p['overlay_sha256'] \
            or sha(out / 'workload.json') != p['workload_sha256'] \
            or sha(out / 'config_runtime.yaml') != p['runtime_sha256'] \
            or sha(out / 'config_hwdb.yaml') != p['hwdb_sha256'] \
            or sha(out / 'native-manager-staged.py') != p['adapter_sha256']:
        raise ValueError('stale or altered stage')
    m = verify(out / 'overlay/root/saturn-spec/bundle', p['identity']['bundle_sha256'], site['readelf'], site['objdump'])
    expected = {'role': m['role'], 'benchmark': m['benchmark'], 'input_id': m['input_id'],
                'worker_id': site['worker_id'], 'agfi': AGFI, 'driver_sha256': DRIVER_SHA,
                'vlen_bits': 256, 'protocol': 'busybox-time-posix-elapsed-v1'}
    if any(p['identity'].get(k) != value for k, value in expected.items()) \
            or p['expected_bootbinary_sha256'] != site['artifacts']['base_bootbinary']['sha256'] \
            or p['name'] != 'saturn-spec-' + p['image_id'][:24]:
        raise ValueError('stage role/platform/image binding differs')
    script = (out / 'overlay/root/saturn-spec/run.sh').read_text()
    if script != runner(m, p['identity']) or p['image_id'] != canonical({
            'identity': p['identity'], 'runner_sha256': hashlib.sha256(script.encode()).hexdigest()}):
        raise ValueError('stale image identity or runner')
    identity = read_json(out / 'overlay/root/saturn-spec/stage-identity.json')
    if identity != {'image_id': p['image_id'], **p['identity']}:
        raise ValueError('stage identity mismatch')
    return p


def verify_image(directory, rootfs, bootbinary):
    """Admit a later externally constructed image by inspecting required ext4 bytes.

    This reads an existing image with debugfs; it does not construct or mount one.
    """
    p = verify_stage(directory)
    rootfs, bootbinary = Path(rootfs), Path(bootbinary)
    if rootfs.is_symlink() or bootbinary.is_symlink() or sha(bootbinary) != p['expected_bootbinary_sha256']:
        raise ValueError('wrong image bootbinary')
    with tempfile.TemporaryDirectory() as tmp:
        for name, expected in p['overlay_sha256'].items():
            destination = Path(tmp) / 'dump'
            destination.unlink(missing_ok=True)
            subprocess.run(['debugfs', '-R', 'dump -p /' + relative(name) + ' ' + str(destination), str(rootfs)],
                           check=True, capture_output=True, timeout=120)
            if not destination.is_file() or sha(destination) != expected:
                raise ValueError('stale image or missing overlay bytes')
    return {'schema_version': 1, 'image_id': p['image_id'], 'plan_sha256': sha(Path(directory) / 'plan.json'),
            'rootfs': str(rootfs.resolve()), 'rootfs_sha256': sha(rootfs),
            'bootbinary': str(bootbinary.resolve()), 'bootbinary_sha256': sha(bootbinary),
            'runtime_sha256': p['runtime_sha256']}
