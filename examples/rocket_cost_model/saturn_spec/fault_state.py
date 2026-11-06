"""Read private RV64 fault snapshots. Never emits memory contents or performance."""
import json
import struct
from pathlib import Path

REGISTERS = 'pc ra sp gp tp t0 t1 t2 s0 s1 a0 a1 a2 a3 a4 a5 a6 a7 s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6'.split()
# Matching final-loop hit, corrected by handoff 6233711.
QEMU = {'pc': 0x11e80, 'a4': 0xf2344, 's1': 0x144, 't2': 1,
        'vl': 1, 'vtype': 0x17, 'vstart': 0}


def decode(directory):
    root = Path(directory)
    gpr = (root / 'fault.gpr').read_bytes()
    sig = (root / 'fault.siginfo').read_bytes()
    if len(gpr) != 256 or len(sig) != 128:
        raise ValueError('expected Linux RV64 GPR/siginfo ABI')
    regs = dict(zip(REGISTERS, struct.unpack('<32Q', gpr)))
    signo, error, code = struct.unpack_from('<iii', sig)
    meta = json.loads((root / 'fault.meta.json').read_text())
    if not meta.get('captured_before_delivery') or meta['signal'] != signo or meta['si_code'] != code:
        raise ValueError('inconsistent first-fault metadata')
    vector = root / 'fault.vector'
    if vector.exists():
        data = vector.read_bytes()
        if len(data) < 40:
            raise ValueError('truncated RVV regset')
        regs.update(zip(('vstart', 'vl', 'vtype', 'vcsr', 'vlenb'), struct.unpack_from('<5Q', data)))
    selected = {k: regs[k] for k in ('pc', 'a2', 'a4', 's1', 't2', 'a3', 's8', 's5', 's0',
                                    'vl', 'vtype', 'vstart', 'vlenb') if k in regs}
    return {'registers': selected, 'signal': signo, 'si_code': code,
            'si_addr': struct.unpack_from('<Q', sig, 16)[0], 'vector_errno': meta['vector_errno']}


def compare(state):
    regs = state['registers']
    if state['signal'] != 11 or state['si_code'] <= 0 or regs['pc'] != QEMU['pc']:
        return {'outcome': 'different_or_nonhardware_fault', 'qemu': QEMU}
    if not {'vl', 'vtype', 'vstart'}.issubset(regs):
        return {'outcome': 'insufficient_vector_fault_state', 'qemu': QEMU}
    matches = {key: regs[key] == value for key, value in QEMU.items()}
    addresses = [regs['a4'] + i * regs['s1'] for i in range(regs['vl'])] if regs['vl'] <= 32 else []
    valid = bool(addresses) and all(a % 4 == 0 and 0xf1910 <= a and a + 4 <= 0xf2474 for a in addresses)
    same_page = bool(addresses) and len({a // 4096 for a in addresses}) == 1
    # vstart is measured after the fault but the QEMU record is pre-instruction.
    # A partial load may legitimately advance it before a spurious fault.
    same = all(matches[k] for k in ('pc', 'a2', 'a4', 's1', 'vl', 'vtype')) and valid and same_page
    return {'outcome': 'matching_valid_addresses_false_fault_evidence' if same else 'execution_divergence',
            'matches': matches, 'element_addresses': addresses, 'within_object': valid,
            'single_page': same_page, 'qemu': QEMU}
