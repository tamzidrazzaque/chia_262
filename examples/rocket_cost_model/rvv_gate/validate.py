"""Validate collected platform evidence; no QEMU or performance fallback."""

import re


def validate(output, expected_binary_sha256, uart, manager_success):
    if not manager_success:
        raise ValueError('manager did not complete successfully')
    required = ('status', 'result.txt', 'binary.sha256', 'cpuinfo.txt')
    if any(name not in output for name in required):
        raise ValueError('incomplete RVV output collection')
    if output['status'].strip() != '0':
        raise ValueError('guest RVV test failed')
    digest = output['binary.sha256'].split()
    if not digest or digest[0] != expected_binary_sha256:
        raise ValueError('guest executable identity differs')
    text = output['result.txt']
    if text.count('RVV_GATE_PASS') != 1 or 'RVV_GATE_FAIL' in text:
        raise ValueError('missing or conflicting test result')
    def number(key):
        values = re.findall(r'^' + re.escape(key) + r'=(\d+)\s*$', text, re.M)
        if len(values) != 1:
            raise ValueError('missing or duplicate ' + key)
        return int(values[0])
    if number('RVV_GATE_VLEN_BITS') != 256:
        raise ValueError('expected VLEN 256')
    if not re.search(r'^RVV_GATE_FULL=0 RVV_GATE_TAIL=0\s*$', text, re.M):
        raise ValueError('vector load/add/store self-check failed')
    before, after = number('RVV_GATE_CYCLE_BEFORE'), number('RVV_GATE_CYCLE_AFTER')
    if not 0 < before < after:
        raise ValueError('invalid target cycle counters')
    cpu = output['cpuinfo.txt']
    if re.findall(r'^processor\s*:\s*(\d+)', cpu, re.M) != ['0']:
        raise ValueError('expected one processor')
    isa = re.findall(r'^isa\s*:\s*(\S+)', cpu, re.M)
    if len(isa) != 1 or not isa[0].startswith('rv64') or 'v' not in isa[0][4:].split('_')[0]:
        raise ValueError('guest did not expose RV64 V')
    if 'reboot: Power down' not in uart:
        raise ValueError('guest shutdown not collected')
    return {'status': 'passed', 'backend': 'fpga', 'vlen_bits': 256,
            'vector_full_and_tail_checks': True, 'guest_binary_sha256': expected_binary_sha256,
            'cycle_before': before, 'cycle_after': after, 'cycle_delta': after - before,
            'single_core': True, 'guest_shutdown': True}
