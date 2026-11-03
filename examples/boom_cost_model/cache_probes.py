"""Validate a capacity sweep; no cache-miss or compiler-win claims from QEMU."""

import json

SIZES_KIB = (8, 16, 32, 64, 256, 1024, 4096, 16384)
RECIPE_VERSION = "cache-working-set-v1"


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
        if record.get('correct') is not True or record.get('line_bytes') != 64 or \
                record.get('loads') != 2 * count or record.get('checksum') != count * (count - 1) or \
                type(record.get('elapsed_ns')) is not int or record['elapsed_ns'] <= 0:
            raise ValueError('cache probe checksum, completion or timer failed')
    if seen != expected:
        raise ValueError('missing cache probe case')
    return records
