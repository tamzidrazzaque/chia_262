import pytest

from examples.rocket_cost_model.rvv_gate.validate import validate


@pytest.fixture
def output():
    return {'status': '0\n', 'binary.sha256': 'a' * 64 + '  /root/rvv-gate-smoke\n',
            'cpuinfo.txt': 'processor : 0\nisa : rv64imafdcv_zicsr\n',
            'result.txt': 'RVV_GATE_VLEN_BITS=256\nRVV_GATE_FULL=0 RVV_GATE_TAIL=0\n'
                          'RVV_GATE_CYCLE_BEFORE=100\nRVV_GATE_CYCLE_AFTER=200\nRVV_GATE_PASS\n'}


def test_accept_complete_hardware_evidence(output):
    assert validate(output, 'a' * 64, 'reboot: Power down', True)['cycle_delta'] == 100


@pytest.mark.parametrize('key,old,new', [
    ('result.txt', 'VLEN_BITS=256', 'VLEN_BITS=128'),
    ('result.txt', 'TAIL=0', 'TAIL=2'),
    ('result.txt', 'CYCLE_AFTER=200', 'CYCLE_AFTER=99'),
    ('result.txt', 'RVV_GATE_PASS', 'RVV_GATE_FAIL'),
    ('cpuinfo.txt', 'rv64imafdcv', 'rv64imafdc'),
    ('cpuinfo.txt', 'processor : 0', 'processor : 1'),
    ('status', '0', '1'),
    ('binary.sha256', 'a' * 64, 'b' * 64),
])
def test_reject_wrong_hardware_or_failed_check(output, key, old, new):
    output[key] = output[key].replace(old, new)
    with pytest.raises(ValueError):
        validate(output, 'a' * 64, 'reboot: Power down', True)


def test_require_collection_manager_and_shutdown(output):
    for uart, success in [('', True), ('reboot: Power down', False)]:
        with pytest.raises(ValueError):
            validate(output, 'a' * 64, uart, success)
    del output['status']
    with pytest.raises(ValueError):
        validate(output, 'a' * 64, 'reboot: Power down', True)
