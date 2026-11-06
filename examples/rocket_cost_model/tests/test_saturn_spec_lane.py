"""Intake/staging unit fixtures are not SPEC programs or performance tests."""

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from examples.rocket_cost_model.saturn_spec import bundle as b, staging as s, results as r
from examples.rocket_cost_model.spec_vector_baseline import role_settings


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


@pytest.fixture
def incoming(tmp_path, monkeypatch):
    root = tmp_path / 'incoming'
    for name, data in {'payload/program': b'ELF unit fixture, never executed',
                       'payload/input.dat': b'input fixture\n', 'reference/s.txt': b'answer fixture\n',
                       'metadata/validation.log': b' Success 648.exchange2_s base test fixture\n'}.items():
        p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    monkeypatch.setattr(b, 'EXCHANGE2_BASELINES', {'1-scalar': b.sha(root / 'payload/program'), '2-generic-vector': b.sha(root / 'payload/program')})
    monkeypatch.setattr(b, 'EXCHANGE2_REFERENCE_SHA', b.sha(root / 'reference/s.txt'))
    monkeypatch.setattr(b, 'EXCHANGE2_REFERENCE_BYTES', (root / 'reference/s.txt').stat().st_size)
    monkeypatch.setattr(b, 'BASELINE_GCC_SHA', 'a' * 64)
    compiler = {'gcc_version': '15.1.0', 'gcc_revision': b.GCC_REVISION,
                'role': '2-generic-vector', 'target_flags': role_settings('2-generic-vector')[1],
                'compiler_sha256': 'a' * 64, 'snapshot_id': 'b' * 64, 'candidate_id': None}
    isa = {'elf_sha256': b.sha(root / 'payload/program'), 'abi': 'lp64d', 'linkage': 'static',
           'vlen_bits': 256, 'dlen_bits': 128,
           'riscv_arch': 'rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zvbb1p0_zvl128b1p0',
           'static_rvv_instruction_count': 4}
    write(root / 'metadata/compiler.json', compiler); write(root / 'metadata/isa.json', isa)
    m = {'schema_version': 1, 'role': '2-generic-vector', 'candidate_id': None,
         'benchmark': '648.exchange2_s', 'input_id': 'test-input-1', 'size': 'test',
         'source_variant': b.SOURCE, 'target': b.TARGET.copy(), 'executable': 'payload/program',
         'compiler_manifest': 'metadata/compiler.json', 'isa_metadata': 'metadata/isa.json',
         'validation_manifest': 'metadata/validation.json', 'inputs': {'input.dat': 'payload/input.dat'},
         'expected_outputs': {'s.txt': 'reference/s.txt'},
         'argv': ['./program', 'input.dat', "quoted';not-shell"], 'stdin': None,
         'stdout': 'stdout.txt', 'stderr': 'stderr.txt'}
    validation = {'status': 'passed', 'spec_validation': 'passed', 'backend': 'qemu',
        **{k: m[k] for k in ['role', 'benchmark', 'size', 'input_id', 'source_variant']},
        'target_vlen': 256, 'target_dlen': 128, 'elf_sha256': isa['elf_sha256'],
        'compiler_manifest_sha256': b.sha(root / m['compiler_manifest']),
        'isa_metadata_sha256': b.sha(root / m['isa_metadata']),
        'inputs_sha256': {k: b.sha(root / p) for k, p in m['inputs'].items()},
        'expected_outputs_sha256': {k: b.sha(root / p) for k, p in m['expected_outputs'].items()},
        'invocation_sha256': b.canonical({k: m[k] for k in ('argv', 'stdin', 'stdout', 'stderr')}),
        'validation_log': 'metadata/validation.log'}
    write(root / m['validation_manifest'], validation)
    m['files_sha256'] = {p.relative_to(root).as_posix(): b.sha(p) for p in root.rglob('*') if p.is_file()}
    write(root / 'manifest.json', m)
    monkeypatch.setattr(b, 'inspect_elf', lambda *args: {k: isa[k] for k in ('riscv_arch', 'static_rvv_instruction_count')})
    return root, m


def verify(root):
    return b.verify(root, b.sha(root / 'manifest.json'), 'readelf-not-executed', 'objdump-not-executed')


def test_full_intake_and_no_overwrite(incoming, tmp_path):
    root, m = incoming
    snapshot = b.intake(root, tmp_path / 'verified', b.sha(root / 'manifest.json'), 'readelf', 'objdump')
    assert verify(snapshot / 'bundle') == m
    with pytest.raises(FileExistsError):
        b.intake(root, tmp_path / 'verified', b.sha(root / 'manifest.json'), 'readelf', 'objdump')


@pytest.mark.parametrize('change', ['file_hash', 'missing_hash', 'extra_file', 'symlink', 'escape',
    'target_scalar', 'vlen128', 'GCC13', 'wrong_flags', 'wrong_isa', 'validation_vlen128',
    'validation_failed', 'stale_input', 'missing_expected', 'shell_executable', 'path_collision'])
def test_reject_invalid_bundle(incoming, change):
    root, m = incoming
    if change == 'file_hash': (root / 'payload/input.dat').write_bytes(b'changed')
    elif change == 'missing_hash': del m['files_sha256']['payload/input.dat']
    elif change == 'extra_file': (root / 'unlisted').write_bytes(b'extra')
    elif change == 'symlink': (root / 'payload/input.dat').unlink(); (root / 'payload/input.dat').symlink_to(root / 'payload/program')
    elif change == 'escape': m['inputs'] = {'../escape': 'payload/input.dat'}
    elif change == 'target_scalar': m['target']['agfi'] = 'agfi-033a86c6e5d006fc8'
    elif change == 'vlen128': m['target']['vlen_bits'] = 128
    elif change in ('GCC13', 'wrong_flags'):
        path = root / m['compiler_manifest']; d = b.read_json(path)
        d['gcc_version' if change == 'GCC13' else 'target_flags'] = '13.2.0' if change == 'GCC13' else '-O0'
        write(path, d); m['files_sha256'][m['compiler_manifest']] = b.sha(path)
    elif change == 'wrong_isa':
        path = root / m['isa_metadata']; d = b.read_json(path); d['riscv_arch'] += '_zvl512b1p0'
        write(path, d); m['files_sha256'][m['isa_metadata']] = b.sha(path)
    elif change in ('validation_vlen128', 'validation_failed', 'stale_input'):
        path = root / m['validation_manifest']; d = b.read_json(path)
        if change == 'validation_vlen128': d['target_vlen'] = 128
        elif change == 'validation_failed': d['status'] = 'failed'
        else: d['inputs_sha256'] = {'input.dat': 'c' * 64}
        write(path, d); m['files_sha256'][m['validation_manifest']] = b.sha(path)
    elif change == 'missing_expected': m['expected_outputs'] = {}
    elif change == 'shell_executable': m['argv'][0] = '/bin/sh'
    elif change == 'path_collision': m['stdout'] = 'program'
    write(root / 'manifest.json', m)
    with pytest.raises(ValueError): verify(root)


def test_require_external_manifest_hash_and_unique_json(incoming):
    root, _ = incoming
    with pytest.raises(ValueError): b.verify(root, 'd' * 64, 'readelf', 'objdump')
    (root / 'manifest.json').write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError): verify(root)


def test_recheck_snapshot_after_copy(incoming, tmp_path, monkeypatch):
    root, _ = incoming
    original = b.shutil.copytree
    def changing_copy(src, dest, *args, **kw):
        result = original(src, dest, *args, **kw)
        if Path(src) == root:
            (Path(dest) / 'payload/input.dat').write_bytes(b'changed during copy')
        return result
    monkeypatch.setattr(b.shutil, 'copytree', changing_copy)
    key = b.sha(root / 'manifest.json')
    with pytest.raises(ValueError): b.intake(root, tmp_path / 'verified', key, 'r', 'o')
    assert (tmp_path / 'verified' / key / 'REJECTED').exists()


@pytest.fixture
def staged(incoming, tmp_path, monkeypatch):
    root, _ = incoming
    artifact = tmp_path / 'artifacts'; artifact.mkdir()
    probe = artifact / 'probe'; probe.write_bytes(b'reused accepted probe fixture')
    bundle = artifact / 'driver.tar.gz'; bundle.write_bytes(b'accepted bundle fixture')
    runtime = artifact / 'runtime.yaml'
    runtime.write_text(yaml.safe_dump({'run_farm': {}, 'metasimulation': {}, 'target_config': {}, 'workload': {}}))
    adapter = artifact / 'native-manager.py'
    adapter.write_text("runtime='config_runtime_saturn_gate.yaml'\nhwdb='config_hwdb.yaml'\n")
    platform = tmp_path / 'platform.json'
    site = {'chipyard_root': str(tmp_path / 'chipyard'), 'worker_id': 'unit-worker', 'worker_ip': '127.0.0.1',
            'ssh_key': '/unit/key', 'known_hosts': '/unit/known_hosts',
            'readelf': 'not-executed', 'objdump': 'not-executed', 'artifacts': {
                k: {'path': str(p), 'sha256': b.sha(p)} for k, p in {
                    'rvv_probe': probe, 'native_manager_adapter': adapter, 'driver_bundle': bundle,
                    'runtime_template': runtime, 'base_bootbinary': probe, 'base_rootfs': probe}.items()}}
    write(platform, site)
    monkeypatch.setattr(s, 'verify_platform', lambda path: site)
    snapshot = b.intake(root, tmp_path / 'verified', b.sha(root / 'manifest.json'), 'r', 'o')
    out = tmp_path / 'staging'
    plan = s.stage(snapshot, platform, out, 'baseline', 0)
    return out, plan, site


def test_stage_only_and_hashes(staged):
    out, p, _ = staged
    assert s.verify_stage(out) == p
    assert p['state'] == 'staged_only_not_constructed'
    assert not list(out.rglob('*.img'))
    assert yaml.safe_load((out / 'config_runtime.yaml').read_text())['metasimulation']['metasimulation_enabled'] is False
    hwdb = yaml.safe_load((out / 'config_hwdb.yaml').read_text())
    assert next(iter(hwdb.values()))['driver_tar'].startswith('file://')
    subprocess.run(['sh', '-n', str(out / 'overlay/root/saturn-spec/run.sh')], check=True)


@pytest.mark.parametrize('file', ['overlay/root/saturn-spec/run.sh', 'overlay/root/saturn-spec/bundle/payload/input.dat',
                                 'config_runtime.yaml', 'config_hwdb.yaml', 'native-manager-staged.py'])
def test_reject_stale_stage(staged, file):
    out, _, _ = staged
    with (out / file).open('ab') as f: f.write(b'changed')
    with pytest.raises(ValueError): s.verify_stage(out)


def test_read_image_rejects_old_overlay(staged, tmp_path, monkeypatch):
    out, _, site = staged
    image = tmp_path / 'existing.img'; image.write_bytes(b'unit fixture, not a guest image')
    def debugfs(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0)  # missing requested file, like an old image
    monkeypatch.setattr(s.subprocess, 'run', debugfs)
    with pytest.raises(ValueError): s.verify_image(out, image, site['artifacts']['base_bootbinary']['path'])


@pytest.fixture
def collected(staged, tmp_path):
    out, p, site = staged
    root = tmp_path / 'collected'; result = root / 'result'; result.mkdir(parents=True)
    data = {'job.status': '0', 'collection.status': '0', 'identity.json': json.dumps(p['identity']),
            'cpuinfo.txt': 'processor : 0\nisa : rv64imafdcv_zicsr\n',
            'probe.txt': 'RVV_GATE_VLEN_BITS=256\nRVV_GATE_FULL=0 RVV_GATE_TAIL=0\nRVV_GATE_CYCLE_BEFORE=100\nRVV_GATE_CYCLE_AFTER=200\nRVV_GATE_PASS\n',
            'probe.sha256': p['overlay_sha256']['root/saturn-spec/rvv-probe'] + '  probe\n',
            'executable.sha256': b.sha(out / 'overlay/root/saturn-spec/bundle/payload/program') + '  program\n',
            'time.txt': 'real 1.25\nuser 1.00\nsys 0.25\n', 'outputs/stdout.txt': 'answer fixture\n',
            'outputs/stderr.txt': '', 'outputs/s.txt': 'answer fixture\n'}
    for name, text in data.items():
        f = result / name; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text)
    (root / 'uartlog').write_text('reboot: Power down\n*** PASSED *** after 1000 cycles\n')
    image_file = tmp_path / 'rootfs'; image_file.write_bytes(b'image fixture')
    boot = Path(site['artifacts']['base_bootbinary']['path'])
    image = tmp_path / 'image.json'
    write(image, {'image_id': p['image_id'], 'plan_sha256': b.sha(out / 'plan.json'),
        'runtime_sha256': p['runtime_sha256'], 'rootfs': str(image_file), 'rootfs_sha256': b.sha(image_file),
        'bootbinary': str(boot), 'bootbinary_sha256': b.sha(boot)})
    preflight = tmp_path / 'preflight.json'
    write(preflight, {'checked_at': 1000, 'platform_sha256': p['identity']['platform_sha256'],
                     'worker': {'idle': True, 'instance_id': 'unit-worker', 'agfi': b.AGFI, 'driver_sha256': b.DRIVER_SHA}})
    completion = tmp_path / 'completion.json'
    write(completion, {'backend': 'fpga', 'task': 'runworkload', 'returncode': 0, 'image_id': p['image_id'],
        'worker_id': 'unit-worker', 'worker_lease_held': True, 'agfi': b.AGFI, 'driver_sha256': b.DRIVER_SHA,
        'vlen_bits': 256, 'phase': 'baseline', 'sample': 0, 'started_at': 1001, 'finished_at': 1002,
        'plan_sha256': b.sha(out / 'plan.json'), 'image_receipt_sha256': b.sha(image), 'preflight_sha256': b.sha(preflight)})
    return out, image, completion, preflight, root, tmp_path / 'result'


def test_collect_bound_correct_outputs(collected):
    assert r.collect(*collected)['target_guest_elapsed_seconds'] == 1.25


@pytest.mark.parametrize('change', ['wrong_output', 'vlen', 'stale_identity', 'no_shutdown', 'zero_time',
                                   'failed_job', 'failed_collection', 'manager', 'driver', 'phase', 'lease', 'expired'])
def test_reject_unusable_result(collected, change):
    out, image, completion, preflight, root, dest = collected
    paths = {'wrong_output': ('outputs/s.txt', 'wrong'), 'vlen': ('probe.txt', 'RVV_GATE_VLEN_BITS=128\n'),
             'stale_identity': ('identity.json', '{}'), 'zero_time': ('time.txt', 'real 0\nuser 0\nsys 0\n'),
             'failed_job': ('job.status', '1'), 'failed_collection': ('collection.status', '1')}
    if change in paths:
        path, value = paths[change]; (root / 'result' / path).write_text(value)
    elif change == 'no_shutdown': (root / 'uartlog').write_text('no shutdown')
    else:
        d = b.read_json(completion)
        key, value = {'manager': ('returncode', 1), 'driver': ('driver_sha256', '0' * 64),
                      'phase': ('phase', 'confirmation'), 'lease': ('worker_lease_held', False),
                      'expired': ('started_at', 1400)}[change]
        d[key] = value; write(completion, d)
    with pytest.raises(ValueError): r.collect(*collected)


def test_no_dispatch_or_build_cli():
    import sys
    from examples.rocket_cost_model.saturn_spec.__main__ import main
    for command in ('run', 'build', 'build-gcc', 'build-spec'):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sys, 'argv', ['saturn-spec', command])
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2


def test_source_status_only_allows_named_runtime_installs():
    from examples.rocket_cost_model.saturn_spec.platform import validate_source_status
    validate_source_status('?? deploy/workloads/saturn-spec-' + 'a' * 24 + '.json\n', 'sims/firesim')
    for status in [' M sim/src/main/scala/Changed.scala\n', '?? sim/new.scala\n',
                   '?? deploy/workloads/unknown.json\n']:
        with pytest.raises(ValueError): validate_source_status(status, 'sims/firesim')


def test_execution_guard_refuses_unconstructed_guest(staged, monkeypatch):
    from examples.rocket_cost_model.saturn_spec import execution
    guard = execution.guard
    out, _, site = staged
    monkeypatch.setattr(execution, "verify_platform", lambda path: site)
    # Fails locally before any SSH or manager command is possible.
    with pytest.raises(FileNotFoundError):
        with guard(out, 'runworkload'):
            pytest.fail('cannot execute an unconstructed guest')


def test_hardlinked_input_rejected(incoming):
    import os
    root, _ = incoming
    p = root / 'payload/input.dat'
    os.link(p, root.parent / 'external-link')
    with pytest.raises(ValueError, match='hard links'): verify(root)


def test_independent_elf_audit_rejects_legacy_gcc(monkeypatch, tmp_path):
    def read_tool(argv, **kwargs):
        option = argv[1]
        output = {'-h': 'ELF64 little endian RISC-V double-float ABI', '-A': 'Tag_RISCV_arch: "rv64i2p1"',
                  '-l': 'LOAD', '-p': 'GCC: (GNU) 13.2.0'}[option]
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')
    monkeypatch.setattr(b.subprocess, 'run', read_tool)
    with pytest.raises(ValueError, match='GCC 15.1'):
        b.inspect_elf(tmp_path / 'not-executed', 'readelf', 'objdump')


def test_preflight_refuses_busy_worker(monkeypatch, tmp_path):
    from examples.rocket_cost_model.saturn_spec import platform
    site = {'worker_id': 'unit-worker', 'worker_ip': '127.0.0.1', 'ssh_key': '/private/key', 'known_hosts': '/private/known_hosts'}
    monkeypatch.setattr(platform, 'verify_platform', lambda path: site)
    def busy(argv, **kwargs):
        assert 'StrictHostKeyChecking=yes' in argv
        assert 'flock -n' in argv[-1]
        raise subprocess.CalledProcessError(1, argv, stderr='worker lock occupied')
    monkeypatch.setattr(platform.subprocess, 'run', busy)
    with pytest.raises(subprocess.CalledProcessError): platform.preflight(tmp_path / 'platform.json')


@pytest.mark.parametrize("exit_code", [0, 2])
def test_native_guard_records_real_task_and_prevents_reuse(collected, staged, monkeypatch, exit_code):
    import io
    import time
    from examples.rocket_cost_model.saturn_spec import execution
    out, image, _, preflight, _, _ = collected
    _, plan, site = staged
    monkeypatch.setattr(execution, 'verify_platform', lambda path: site)
    write(out / 'image-receipt.json', b.read_json(image))
    pf = b.read_json(preflight); pf['checked_at'] = time.time(); write(out / 'preflight.json', pf)
    image_data = b.read_json(image)
    installed = Path(site['chipyard_root']) / 'sims/firesim/deploy/workloads' / (plan['name'] + '.json')
    write(installed, {'benchmark_name': plan['name'], 'common_rootfs': image_data['rootfs'],
                      'common_bootbinary': image_data['bootbinary']})
    class Lease:
        def __init__(self):
            self.stdin = io.StringIO(); self.stdout = io.StringIO('SATURN_SPEC_LEASE\n'); self.stderr = io.StringIO()
        def poll(self): return None
        def wait(self, timeout): return 0
    monkeypatch.setattr(execution.subprocess, 'Popen', lambda *args, **kw: Lease())
    monkeypatch.setattr(execution.subprocess, 'run', lambda *args, **kw: subprocess.CompletedProcess(args, 0))
    with execution.guard(out, 'infrasetup'):
        pass  # no real manager or hardware is invoked by this unit fixture
    with pytest.raises(SystemExit):
        with execution.guard(out, 'runworkload'):
            raise SystemExit(exit_code)
    completed = b.read_json(out / 'runworkload-completion.json')
    assert completed['returncode'] == exit_code and completed['worker_lease_held']
    with pytest.raises(ValueError, match='already attempted'):
        with execution.guard(out, 'runworkload'): pass


def test_reject_stale_validated_invocation(incoming):
    root, m = incoming
    m['argv'].append('different-work-size')
    write(root / 'manifest.json', m)
    with pytest.raises(ValueError, match='producer validation'): verify(root)


def test_stage_rejects_swapped_platform_binding(staged):
    out, plan, _ = staged
    plan['expected_bootbinary_sha256'] = '0' * 64
    write(out / 'plan.json', plan)
    with pytest.raises(ValueError, match='binding differs'): s.verify_stage(out)


@pytest.fixture
def published_archive(tmp_path, monkeypatch):
    import io
    import tarfile
    from examples.rocket_cost_model.saturn_spec import published
    data = {'roles/1-scalar/exchange2_s': b'scalar unit fixture, never executable',
            'roles/2-generic-vector/exchange2_s': b'vector unit fixture, never executable',
            'inputs/puzzles.txt': b'unit fixture', 'inputs/control': b'0\n',
            'expected/s.txt': b'x' * 855}
    hashes = {k: __import__('hashlib').sha256(v).hexdigest() for k, v in data.items()}
    monkeypatch.setattr(published, 'PUBLISHED_ELFS', {r: hashes['roles/' + r + '/exchange2_s']
                                                    for r in ('1-scalar', '2-generic-vector')})
    monkeypatch.setattr(published, 'PUBLISHED_OUTPUT', hashes['expected/s.txt'])
    manifest = {'schema_version': 1, 'workload': {'benchmark': '648.exchange2_s', 'size': 'test', 'source': 'SPEC CPU2017'},
        'target': {'config': 'REFV256D128RocketConfig', 'firesim_config': 'FireSimREFV256D128RocketConfig', 'vlen': 256, 'dlen': 128},
        'roles': {r: {'label': role_settings(r)[0], 'target_flags': role_settings(r)[1],
                      'archive_path': 'roles/' + r + '/exchange2_s', 'binary_sha256': h}
                  for r, h in published.PUBLISHED_ELFS.items()},
        'files': {k: {'sha256': hashes[k], 'bytes': len(data[k])} for k in ('inputs/puzzles.txt', 'inputs/control', 'expected/s.txt')}}
    data['manifest.json'] = json.dumps(manifest).encode()
    path = tmp_path / 'unit.tar'
    with tarfile.open(path, 'w') as tf:
        for name, content in data.items():
            info = tarfile.TarInfo(name); info.size = len(content); tf.addfile(info, io.BytesIO(content))
    monkeypatch.setattr(published, 'PUBLISHED_ARCHIVE_SHA', b.sha(path))
    monkeypatch.setattr(published, 'inspect_elf', lambda p, *args: {
        'riscv_arch': 'unit-audit-not-real-ELF', 'static_rvv_instruction_count': 0 if '1-scalar' in str(p) else 5452})
    return path


def test_published_archive_is_only_quarantined(published_archive, tmp_path):
    from examples.rocket_cost_model.saturn_spec import published
    dest = published.intake_archive(published_archive, tmp_path / 'quarantine', 'r', 'o')
    receipt = b.read_json(dest / 'PENDING_METADATA.json')
    assert receipt['image_staging_allowed'] is False
    assert receipt['state'] == 'payload_verified_pending_required_metadata'
    assert not (dest / 'intake.json').exists()


def test_published_archive_rejects_changed_bytes(published_archive, tmp_path):
    from examples.rocket_cost_model.saturn_spec import published
    with published_archive.open('ab') as f: f.write(b'tampered')
    with pytest.raises(ValueError, match='published'):
        published.intake_archive(published_archive, tmp_path / 'quarantine', 'r', 'o')


def test_reject_nonbaseline_compiler_hash(incoming):
    root, m = incoming
    p = root / m['compiler_manifest']; c = b.read_json(p); c['compiler_sha256'] = 'f' * 64
    write(p, c); m['files_sha256'][m['compiler_manifest']] = b.sha(p)
    write(root / 'manifest.json', m)
    with pytest.raises(ValueError, match='baseline compiler hash'): verify(root)
