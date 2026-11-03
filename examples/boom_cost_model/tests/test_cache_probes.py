import json
from pathlib import Path
import shutil
import subprocess

import pytest

from examples.boom_cost_model.cache_probes import SIZES_KIB, validate_cache_probes


@pytest.fixture(scope='module')
def output(tmp_path_factory):
    cc = shutil.which('cc')
    if not cc:
        pytest.skip('C compiler unavailable')
    binary = tmp_path_factory.mktemp('cache-probe') / 'probe'
    source = Path(__file__).parents[1] / 'cache_probe.c'
    subprocess.run([cc, '-O3', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    return subprocess.check_output([str(binary)], timeout=30)


def test_actual_c_traversals_match_independent_reference(output):
    records = validate_cache_probes({'output/job.status': b'0', 'output/probes.jsonl': output}, True)
    assert len(records) == 48
    assert min(SIZES_KIB) * 1024 < 32768 < max(SIZES_KIB) * 1024
    assert max(SIZES_KIB) * 1024 > 4 * 1024**2


@pytest.mark.parametrize('failure', ['guest', 'status', 'missing', 'duplicate', 'checksum', 'timer'])
def test_collection_and_wrong_results_fail_closed(output, failure):
    rows = [json.loads(l) for l in output.splitlines()]
    if failure == 'missing': rows.pop()
    if failure == 'duplicate': rows[-1] = rows[0]
    if failure == 'checksum': rows[0]['checksum'] += 1
    if failure == 'timer': rows[0]['elapsed_ns'] = 0
    files = {'output/job.status': b'1' if failure == 'status' else b'0',
             'output/probes.jsonl': '\n'.join(json.dumps(r) for r in rows).encode()}
    with pytest.raises(ValueError):
        validate_cache_probes(files, failure != 'guest', hardware=True)
