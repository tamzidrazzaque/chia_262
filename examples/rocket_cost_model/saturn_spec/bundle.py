"""Immutable SPEC intake. Never builds a compiler or executes an incoming ELF."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess

from examples.rocket_cost_model.spec_vector_baseline import role_settings, validated

AGFI = 'agfi-012e92467d7d2149a'
DRIVER_SHA = '5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd'
QUINTUPLET = ('f2-firesim-FireSim-FireSimREFV256D128RocketConfig-'
              'WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config')
GCC_REVISION = '1b306039ac49f8ad91ca71d3de3150a3c9fa792a'
TARGET = {'agfi': AGFI, 'driver_sha256': DRIVER_SHA, 'quintuplet': QUINTUPLET,
          'vlen_bits': 256, 'dlen_bits': 128}
FIELDS = {'schema_version', 'role', 'candidate_id', 'benchmark', 'input_id', 'size',
          'source_variant', 'target', 'compiler_manifest', 'isa_metadata',
          'validation_manifest', 'executable', 'inputs', 'expected_outputs',
          'argv', 'stdin', 'stdout', 'stderr', 'files_sha256'}
SOURCE = 'unchanged SPEC CPU2017 source'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('expected a full lowercase SHA-256')
    return value


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError('invalid relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or p.as_posix() != value or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('noncanonical or escaping path')
    if not re.fullmatch(r'[A-Za-z0-9_.+/-]+', value):
        raise ValueError('unsupported filename characters')
    return value


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def regular_tree(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('bundle must be a real directory, not an archive or link')
    # Reject links in ancestors too: the intake must have one unambiguous location.
    if any(p.is_symlink() for p in root.absolute().parents):
        raise ValueError('linked intake parent')
    files = set()
    for p in root.rglob('*'):
        entry = p.lstat()
        mode = entry.st_mode
        if stat.S_ISREG(mode) and entry.st_nlink != 1:
            raise ValueError('hard links are forbidden')
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('links and special files are forbidden')
        if p.is_file():
            files.add(relative(p.relative_to(root).as_posix()))
    return files


def inspect_elf(path, readelf, objdump):
    def run(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120).stdout
    header = run(str(readelf), '-h', str(path))
    attrs = run(str(readelf), '-A', str(path))
    segments = run(str(readelf), '-l', str(path))
    comment = run(str(readelf), '-p', '.comment', str(path))
    if not all(x in header for x in ('ELF64', 'little endian', 'RISC-V', 'double-float ABI')):
        raise ValueError('expected little-endian RV64 lp64d ELF')
    if re.search(r'^\s*(INTERP|DYNAMIC)\s', segments, re.M):
        raise ValueError('only static executables are admitted')
    if not re.search(r'GCC:.*\b15\.1\.0\b', comment):
        raise ValueError('missing GCC 15.1 ELF provenance; GCC 13 rebuilds are rejected')
    arch = re.findall(r'Tag_RISCV_arch: "([^"]+)"', attrs)
    if len(arch) != 1:
        raise ValueError('missing or ambiguous ELF ISA attributes')
    assembly = run(str(objdump), '-d', str(path))
    vectors = 0
    for line in assembly.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].endswith(':'):
            if fields[2] in ('.word', '.4byte', '.2byte'):
                raise ValueError('disassembler cannot audit an instruction; use compatible binutils')
            vectors += bool(re.fullmatch(r'v[a-z0-9.]+', fields[2]))
    return {'riscv_arch': arch[0], 'static_rvv_instruction_count': vectors}


def validate_isa(isa, role):
    if isa.get('abi') != 'lp64d' or isa.get('linkage') != 'static' \
            or isa.get('vlen_bits') != 256 or isa.get('dlen_bits') != 128:
        raise ValueError('ISA metadata does not describe the accepted Saturn platform')
    arch = isa.get('riscv_arch', '')
    if not isinstance(arch, str) or not arch.startswith('rv64'):
        raise ValueError('expected RV64 ISA metadata')
    extensions = [re.sub(r'\d+p\d+$', '', part) for part in arch[4:].split('_')]
    if not extensions or not set(extensions[0]) <= set('imafdcv'):
        raise ValueError('unsupported base ISA')
    allowed = {'i', 'm', 'a', 'f', 'd', 'c', 'v', 'zicsr', 'zifencei', 'zicntr',
               'zihpm', 'zmmul', 'zaamo', 'zalrsc', 'zca', 'zcd', 'zvkb', 'zba', 'zbb', 'zbs', 'zve32x', 'zve32f', 'zve64x',
               'zve64f', 'zve64d', 'zvbb', 'zvl32b', 'zvl64b', 'zvl128b', 'zvl256b'}
    extension_set = set(extensions[0]) | set(extensions[1:])
    if not set('imafdc') <= extension_set:
        raise ValueError('ELF does not cover the fixed RV64GC ABI/ISA')
    if not extension_set <= allowed:
        raise ValueError('unsupported extension or minimum vector length')
    count = isa.get('static_rvv_instruction_count')
    if type(count) is not int or count < 0:
        raise ValueError('invalid vector instruction count')
    has_v = 'v' in extension_set
    if role == '1-scalar' and (has_v or count or any(x.startswith(('zve', 'zv')) for x in extension_set)):
        raise ValueError('scalar role contains vector ISA/code')
    if role != '1-scalar' and (not has_v or count == 0):
        raise ValueError('vector role lacks vector code')


def verify(root, manifest_sha256, readelf, objdump):
    root = Path(root)
    files = regular_tree(root)
    if 'manifest.json' not in files or sha(root / 'manifest.json') != digest(manifest_sha256):
        raise ValueError('manifest digest mismatch')
    m = read_json(root / 'manifest.json')
    if set(m) != FIELDS or type(m['schema_version']) is not int or m['schema_version'] != 1:
        raise ValueError('unsupported bundle fields/schema')
    if canonical(m['target']) != canonical(TARGET) or m['source_variant'] != SOURCE:
        raise ValueError('wrong platform or changed SPEC source')
    if not isinstance(m['benchmark'], str) or not re.fullmatch(r'[56]\d{2}\.[A-Za-z0-9_]+_[rs]', m['benchmark']):
        raise ValueError('invalid SPEC benchmark')
    if m['size'] not in ('test', 'train', 'ref') or not isinstance(m['input_id'], str) \
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', m['input_id']):
        raise ValueError('invalid input identity')
    _, flags, _ = role_settings(m['role'], m['candidate_id'])
    hashes = m['files_sha256']
    if not isinstance(hashes, dict) or files != {'manifest.json', *hashes}:
        raise ValueError('missing or unlisted files')
    for name, expected in hashes.items():
        relative(name)
        if sha(root / name) != digest(expected):
            raise ValueError('bundle file digest mismatch: ' + name)
    if 'manifest.json' in hashes:
        raise ValueError('manifest cannot hash itself')
    required = {m[k] for k in ('compiler_manifest', 'isa_metadata', 'validation_manifest', 'executable')}
    for label in ('inputs', 'expected_outputs'):
        mapping = m[label]
        if not isinstance(mapping, dict) or (label == 'expected_outputs' and not mapping):
            raise ValueError('inputs must be a mapping and expected outputs must be nonempty')
        for dest, source in mapping.items():
            relative(dest)
            required.add(relative(source))
    if not required <= hashes.keys():
        raise ValueError('unhashed required file')
    for name in required:
        relative(name)
    # All payload work paths are disjoint from adapters, metadata and each other.
    paths = ['program', m['stdout'], m['stderr'], *m['inputs'], *m['expected_outputs']]
    # Expected stdout/stderr may themselves be correctness outputs.
    work_paths = {'program', m['stdout'], m['stderr'], *m['inputs'], *m['expected_outputs']}
    if m['stdout'] == m['stderr'] or 'program' in (m['stdout'], m['stderr']) or 'program' in m['inputs'] or 'program' in m['expected_outputs'] \
            or set(m['inputs']) & (set(m['expected_outputs']) | {m['stdout'], m['stderr']}):
        raise ValueError('overlapping work paths')
    for name in paths:
        relative(name)
    for a in work_paths:
        if any(b != a and b.startswith(a + '/') for b in work_paths):
            raise ValueError('work file/directory collision')
    if m['stdin'] is not None and m['stdin'] not in m['inputs']:
        raise ValueError('stdin must name an input destination')
    if not isinstance(m['argv'], list) or not m['argv'] or m['argv'][0] != './program' \
            or len(m['argv']) > 256 or any(not isinstance(a, str) or '\x00' in a or len(a) > 8192 for a in m['argv']):
        raise ValueError('expected bounded argv beginning ./program')
    compiler = read_json(root / m['compiler_manifest'])
    if compiler.get('gcc_version') != '15.1.0' or compiler.get('gcc_revision') != GCC_REVISION \
            or compiler.get('role') != m['role'] or compiler.get('target_flags') != flags:
        raise ValueError('wrong compiler revision, role, or fixed flags; GCC 13 rebuilds forbidden')
    digest(compiler.get('compiler_sha256'))
    digest(compiler.get('snapshot_id'))
    candidate = compiler.get('candidate_id')
    if m['role'] == '3-saturn-aware':
        if not digest(candidate).startswith(m['candidate_id']):
            raise ValueError('candidate identity mismatch')
    elif candidate is not None:
        raise ValueError('baseline must not contain a candidate ID')
    isa = read_json(root / m['isa_metadata'])
    if isa.get('elf_sha256') != hashes[m['executable']]:
        raise ValueError('ISA audit refers to a different executable')
    validate_isa(isa, m['role'])
    actual = inspect_elf(root / m['executable'], readelf, objdump)
    if any(actual[k] != isa.get(k) for k in actual):
        raise ValueError('independent ELF audit differs from metadata')
    v = read_json(root / m['validation_manifest'])
    expected = {'status': 'passed', 'spec_validation': 'passed', 'backend': 'qemu',
                'role': m['role'], 'benchmark': m['benchmark'], 'size': m['size'],
                'input_id': m['input_id'], 'target_vlen': 256, 'target_dlen': 128,
                'source_variant': SOURCE, 'elf_sha256': hashes[m['executable']],
                'invocation_sha256': canonical({k: m[k] for k in ('argv', 'stdin', 'stdout', 'stderr')}),
                'compiler_manifest_sha256': hashes[m['compiler_manifest']],
                'isa_metadata_sha256': hashes[m['isa_metadata']],
                'inputs_sha256': {k: hashes[p] for k, p in m['inputs'].items()},
                'expected_outputs_sha256': {k: hashes[p] for k, p in m['expected_outputs'].items()}}
    if any(v.get(k) != value for k, value in expected.items()):
        raise ValueError('producer validation identity/status mismatch')
    log = relative(v.get('validation_log'))
    if log not in hashes or not validated((root / log).read_text(), m['benchmark'], m['size']):
        raise ValueError('missing SPEC success evidence')
    return m


def intake(source, destination, manifest_sha256, readelf, objdump):
    """Copy into a new content-addressed snapshot and verify the copy again."""
    m = verify(source, manifest_sha256, readelf, objdump)
    dest = Path(destination) / digest(manifest_sha256)
    dest.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        shutil.copytree(source, dest / 'bundle', symlinks=True)
        verify(dest / 'bundle', manifest_sha256, readelf, objdump)
        (dest / 'intake.json').write_text(json.dumps({'manifest_sha256': manifest_sha256,
            'role': m['role'], 'benchmark': m['benchmark'], 'input_id': m['input_id']}, indent=2) + '\n')
    except Exception:
        (dest / 'REJECTED').write_text('Do not stage this incomplete intake.\n')
        raise
    return dest
