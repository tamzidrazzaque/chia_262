"""Quarantine the producer's published roles 1/2 archive without inventing metadata."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from .bundle import digest, inspect_elf, read_json, relative, sha
from examples.rocket_cost_model.spec_vector_baseline import role_settings

PUBLISHED_ARCHIVE_SHA = '9c6331dea7f03a6e9364df4305d8ce0dae696ab5f683feb0c37208ce9bdb10ca'
PUBLISHED_ELFS = {'1-scalar': '6500e7e82a183d11d5e83b0ff4b3ee79fc709127c849b8c2fca1675307d27e7d',
                  '2-generic-vector': '933c5062989468d8eba30c72a08dadb2e15bf39dfffff2532f5f2fed5cada541'}
PUBLISHED_OUTPUT = '93c5882eda07b05bf277b4636f8a92cd16bf347e8cf5513fc578b8f60c12506e'


def intake_archive(archive, destination, readelf, objdump):
    archive = Path(archive)
    if archive.is_symlink() or sha(archive) != PUBLISHED_ARCHIVE_SHA:
        raise ValueError('not the published roles 1/2 archive')
    expected_names = {'manifest.json', 'roles/1-scalar/exchange2_s', 'roles/2-generic-vector/exchange2_s',
                      'inputs/puzzles.txt', 'inputs/control', 'expected/s.txt'}
    with tarfile.open(archive, 'r:') as tar:
        members = tar.getmembers()
        names = [relative(m.name) for m in members]
        if len(names) != len(set(names)) or set(names) != expected_names or any(not m.isfile() for m in members):
            raise ValueError('unexpected archive members, duplicate names or links')
        manifest_member = tar.getmember('manifest.json')
        if manifest_member.size > 1024 * 1024:
            raise ValueError('oversized published manifest')
        raw = tar.extractfile(manifest_member).read()
        # Reject duplicate keys just as directory intake does, without extraction.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate archive manifest key')
                result[key] = value
            return result
        m = json.loads(raw, object_pairs_hook=unique)
        if m.get('schema_version') != 1 or m.get('workload') != {
                'benchmark': '648.exchange2_s', 'size': 'test', 'source': 'SPEC CPU2017'} \
                or m.get('target') != {'config': 'REFV256D128RocketConfig',
                    'firesim_config': 'FireSimREFV256D128RocketConfig', 'vlen': 256, 'dlen': 128}:
            raise ValueError('wrong archive workload/target')
        if set(m.get('roles', {})) != set(PUBLISHED_ELFS) or set(m.get('files', {})) != {
                'inputs/puzzles.txt', 'inputs/control', 'expected/s.txt'}:
            raise ValueError('incomplete archive payload manifest')
        hashes = {'manifest.json': hashlib.sha256(raw).hexdigest()}
        for role, expected in PUBLISHED_ELFS.items():
            d = m['roles'][role]
            label, flags, _ = role_settings(role)
            name = 'roles/' + role + '/exchange2_s'
            if d.get('label') != label or d.get('target_flags') != flags \
                    or d.get('archive_path') != name or d.get('binary_sha256') != expected:
                raise ValueError('published role/flags/ELF mismatch')
            hashes[name] = expected
        for name, d in m['files'].items():
            if type(d.get('bytes')) is not int or d['bytes'] < 0 or tar.getmember(name).size != d['bytes']:
                raise ValueError('archive file-size mismatch')
            hashes[name] = digest(d.get('sha256'))
        if hashes['expected/s.txt'] != PUBLISHED_OUTPUT or tar.getmember('expected/s.txt').size != 855:
            raise ValueError('wrong independent Exchange2 reference')
        for name, expected in hashes.items():
            h = hashlib.sha256()
            with tar.extractfile(name) as source:
                for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    h.update(block)
            if h.hexdigest() != expected:
                raise ValueError('archive member hash mismatch')
        dest = Path(destination) / PUBLISHED_ARCHIVE_SHA
        dest.mkdir(parents=True, mode=0o700, exist_ok=False)
        try:
            for name, expected in hashes.items():
                p = dest / 'payload' / name
                p.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                with tar.extractfile(name) as source, p.open('xb') as target:
                    shutil.copyfileobj(source, target)
                if sha(p) != expected:
                    raise ValueError('archive changed during intake')
            if sha(archive) != PUBLISHED_ARCHIVE_SHA:
                raise ValueError('archive changed during intake')
            audits = {role: inspect_elf(dest / 'payload/roles' / role / 'exchange2_s', readelf, objdump)
                      for role in PUBLISHED_ELFS}
            if audits['1-scalar']['static_rvv_instruction_count'] != 0 \
                    or audits['2-generic-vector']['static_rvv_instruction_count'] != 5452:
                raise ValueError('published ELF instruction audit mismatch')
            receipt = {'schema_version': 1, 'archive_sha256': PUBLISHED_ARCHIVE_SHA,
                'state': 'payload_verified_pending_required_metadata', 'image_staging_allowed': False,
                'members_sha256': hashes, 'elf_audits': audits,
                'missing': ['per-role compiler manifest/compiler hash',
                            'per-role validated invocation and metadata/log bindings',
                            'per-role ISA metadata in the complete directory contract']}
            (dest / 'PENDING_METADATA.json').write_text(json.dumps(receipt, indent=2) + '\n')
        except Exception:
            (dest / 'REJECTED').write_text('Do not stage this failed archive intake.\n')
            raise
    return dest
