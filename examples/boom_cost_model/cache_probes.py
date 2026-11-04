"""Validate a capacity sweep; no cache-miss or compiler-win claims from QEMU."""

import json

SIZES_KIB = (8, 16, 32, 64, 256, 1024, 4096, 16384)
RECIPE_VERSION = "cache-working-set-v2-batched-clock"


def validate_cache_probes(outputs, success, hardware=False):
    statuses = [v.strip() for k, v in outputs.items() if k.endswith('/job.status')]
    files = [v for k, v in outputs.items() if k.endswith('/probes.jsonl')]
    if not success or statuses != [b'0'] or len(files) != 1:
        raise ValueError('cache probe guest or result collection failed')
    records = [json.loads(line) for line in files[0].splitlines()]
    expected = {(kernel, kib * 1024, repeat)
        for kernel in ('chase', 'stream') for kib in SIZES_KIB for repeat in range(3)}
    seen = set()
    for record in records:
        key = (record.get('kernel'), record.get('working_set_bytes'), record.get('repeat'))
        if key not in expected or key in seen:
            raise ValueError('missing, unexpected or duplicate cache probe case')
        seen.add(key)
        count = key[1] // 64
        calls = record.get('batch_calls')
        if type(calls) is not int or not 1 <= calls <= 131072 or calls & (calls - 1) or \
                2 * count * calls > 33554432:
            raise ValueError('invalid cache probe batch size')
        if record.get('correct') is not True or record.get('line_bytes') != 64 or \
                record.get('loads') != 2 * count * calls or record.get('checksum') != count * (count - 1) * calls or \
                type(record.get('elapsed_ns')) is not int or record['elapsed_ns'] <= 0:
            raise ValueError('cache probe checksum, completion or timer failed')
    if seen != expected:
        raise ValueError('missing cache probe case')
    return records
