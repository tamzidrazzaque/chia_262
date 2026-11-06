"""Classify bounded first-iteration controls; never a performance result."""
import json
import struct
from pathlib import Path
from .fault_state import REGISTERS


def checkpoint(folder, pc):
    root = Path(folder)
    status = (root / 'capture.status').read_text().strip()
    if status != '0':
        return {'valid': False, 'capture_status': status}
    meta = json.loads((root / 'fault.meta.json').read_text())
    data = (root / 'fault.gpr').read_bytes()
    if len(data) != 256 or meta['signal'] != 5:
        raise ValueError('expected a stopped RV64 software checkpoint')
    regs = dict(zip(REGISTERS, struct.unpack('<32Q', data)))
    vector = (root / 'fault.vector').read_bytes()
    regs.update(zip(('vstart', 'vl', 'vtype', 'vcsr', 'vlenb'), struct.unpack_from('<5Q', vector)))
    if regs['pc'] != pc or regs['vlenb'] != 32:
        raise ValueError('wrong checkpoint or vector platform')
    return {'valid': True, 'registers': {k: regs[k] for k in
        ('pc', 'a0', 'a2', 'a3', 'a4', 't2', 's0', 's1', 's5', 'vl', 'vtype', 'vstart')}}


def multiplication_count(initial, factor, result, bound=16):
    value = initial
    for count in range(bound + 1):
        if value == result:
            return count
        value = (value * factor) % 2**64
    return None


def classify(points):
    names = ('post_mul', 'post_addi', 'mul_stable_source')
    if any(not points[n]['valid'] for n in names):
        return {'outcome': 'incomplete_controls'}
    for name in names:
        regs = points[name]['registers']
        expected = {'pc': 0x11e88, 'a0': 0x144, 'a3': 4, 'a4': 0xf1924,
                    't2': 9, 's0': 0xf1910, 's1': 0x144, 's5': 5,
                    'vl': 4, 'vtype': 0x17, 'vstart': 0}
        if any(regs[k] != v for k, v in expected.items()):
            return {'outcome': 'unmatched_control_context', 'case': name}
    results = {name: points[name]['registers']['a2'] for name in names}
    count = multiplication_count(0x144, 4, results['post_mul'])
    if results == {'post_mul': 0x510, 'post_addi': 0x145, 'mul_stable_source': 0x510}:
        outcome = 'not_reproduced'
    elif count is not None and count > 1 and results['post_addi'] == 0x145 and results['mul_stable_source'] == 0x510:
        outcome = 'iterative_mul_replay_side_effect_pattern'
    elif results['post_addi'] != 0x145:
        outcome = 'scalar_operand_or_generic_replay_unresolved'
    else:
        outcome = 'mul_datapath_or_operand_unresolved'
    return {'outcome': outcome, 'results': results, 'equivalent_mul_applications': count,
            'tested_instruction_pc': 0x11e84,
            'scope': 'first matching loop iteration; private process-text diagnostic variants'}
