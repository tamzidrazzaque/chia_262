import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from examples.rocket_cost_model.saturn_spec import fault_state as f
from examples.rocket_cost_model.saturn_spec import staging as s


def test_register_comparison(tmp_path):
    regs = [0] * 32
    for key, value in f.QEMU.items():
        if key in f.REGISTERS:
            regs[f.REGISTERS.index(key)] = value
    (tmp_path / 'fault.gpr').write_bytes(struct.pack('<32Q', *regs))
    sig = bytearray(128)
    struct.pack_into('<iii', sig, 0, 11, 0, 1)
    struct.pack_into('<Q', sig, 16, 0xf1924)
    (tmp_path / 'fault.siginfo').write_bytes(sig)
    (tmp_path / 'fault.vector').write_bytes(struct.pack('<5Q', 0, 4, 0x17, 0, 32))
    (tmp_path / 'fault.meta.json').write_text(json.dumps({'signal': 11, 'si_code': 1,
        'vector_errno': 0, 'captured_before_delivery': True}))
    state = f.decode(tmp_path)
    assert state['si_addr'] == 0xf1924
    assert f.compare(state)['outcome'] == 'matching_valid_addresses_false_fault_evidence'
    state['registers']['vstart'] = 2
    assert f.compare(state)['outcome'] == 'matching_valid_addresses_false_fault_evidence'
    state['registers']['a4'] += 4
    assert f.compare(state)['outcome'] == 'execution_divergence'
    del state['registers']['vl']
    assert f.compare(state)['outcome'] == 'insufficient_vector_fault_state'


def test_native_capture_original_segv(tmp_path):
    cc = shutil.which('cc')
    if not cc:
        pytest.skip('host compiler unavailable')
    source = Path(s.__file__).with_name('fault_capture.c')
    binary = tmp_path / 'capture'
    subprocess.run([cc, '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    # No core is requested on the host; the guest explicitly enables it separately.
    child = tmp_path / 'child.c'
    child.write_text('int main(void) { *(volatile int *)0 = 1; return 0; }\n')
    program = tmp_path / 'child'
    subprocess.run([cc, str(child), '-o', str(program)], check=True)
    import resource
    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    result = subprocess.run([str(binary), str(tmp_path), str(program)], preexec_fn=no_core, timeout=10)
    assert result.returncode == 11
    sig = (tmp_path / 'fault.siginfo').read_bytes()
    assert struct.unpack_from('<i', sig)[0] == 11
    assert struct.unpack_from('<i', sig, 8)[0] > 0
    assert struct.unpack_from('<Q', sig, 16)[0] == 0
    assert json.loads((tmp_path / 'fault.meta.json').read_text())['captured_before_delivery']
