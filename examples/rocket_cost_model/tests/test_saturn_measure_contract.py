"""Transport contract checks without credentials, SPEC or hardware."""

import hashlib
import json
from unittest.mock import patch, MagicMock

from examples.rocket_cost_model import saturn_measure_hook as hook
from examples.rocket_cost_model.saturn_manager_contract import install_descriptor


def test_transport_contract(tmp_path):
    bundle = tmp_path / 'bundle/3-saturn-aware'
    bundle.mkdir(parents=True)
    (bundle / 'manifest.json').write_text('{}')
    digest = hashlib.sha256(b'{}').hexdigest()
    receipt = {'status': 'correct', 'identity': {'bundle_sha256': digest}}
    calls = []

    def ssh(host, key, command, capture=False):
        calls.append(command)
        if capture:
            marker = command.split(";", 1)[0].split()[-1].strip("'")
            return 'Agent pid 123\n' + marker + '\n' + json.dumps(receipt)
        return ''

    sender = MagicMock()
    sender.wait.return_value = 0
    env = {'SATURN_WORKDIR': str(tmp_path), 'SATURN_CANDIDATE_ID': '3.99',
           'SATURN_MANAGER_HOST': 'fixture', 'SATURN_MANAGER_KEY': '/fixture/key'}
    with patch.dict(hook.os.environ, env), patch.object(hook, 'ssh', ssh), \
            patch.object(hook.subprocess, 'Popen', return_value=sender):
        hook.main()
    # Stage owns directory creation. Collection owns its output directory.
    assert 'test ! -e' in calls[0]
    assert '/staging/auto-3-99' not in calls[0].split('mkdir', 1)[1]
    assert '/collection' in calls[1]
    assert 'tail -n1' not in calls[1]
    assert calls[2].endswith('/collection/result.json')
    assert json.loads((tmp_path / 'candidate-receipt.json').read_text()) == receipt


def test_early_boot_panic_is_retryable_when_simulator_exits_cleanly(tmp_path):
    uart = tmp_path / 'uartlog'
    uart.write_text('Kernel panic - not syncing: Fatal exception in interrupt\n')
    result = tmp_path / 'result'

    failure = hook.retryable_early_boot_failure(uart, result)

    assert failure == {
        'classification': 'early_kernel_panic_before_guest_job',
        'uart_sha256': hashlib.sha256(uart.read_bytes()).hexdigest(),
    }


def test_early_boot_classifier_rejects_workload_failures(tmp_path):
    uart = tmp_path / 'uartlog'
    result = tmp_path / 'result'
    uart.write_text('Kernel panic - not syncing: Fatal exception in interrupt\n')
    result.mkdir()
    assert hook.retryable_early_boot_failure(uart, result) is None

    result.rmdir()
    uart.write_text('Kernel panic - not syncing: Fatal exception in interrupt\n'
                    'SATURN_SPEC_JOB_EXIT=11 COLLECTION=1\n')
    assert hook.retryable_early_boot_failure(uart, result) is None

    uart.write_text('FireSim completed with another guest error\n')
    assert hook.retryable_early_boot_failure(uart, result) is None


def test_descriptor_uses_admitted_bytes(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    deploy = tmp_path / 'deploy'
    (deploy / 'workloads').mkdir(parents=True)
    name = 'saturn-spec-fixture'
    (stage / 'plan.json').write_text(json.dumps({'name': name, 'image_id': 'id'}))
    image = {'image_id': 'id'}
    for field in ('rootfs', 'bootbinary'):
        source = tmp_path / field
        source.write_bytes(field.encode())
        image[field] = str(source)
        image[field + '_sha256'] = hashlib.sha256(field.encode()).hexdigest()
    (stage / 'image-receipt.json').write_text(json.dumps(image))
    descriptor = deploy / 'workloads' / (name + '.json')
    descriptor.write_text(json.dumps({'benchmark_name': name}))
    install_descriptor(stage, deploy)
    value = json.loads(descriptor.read_text())
    base = deploy / 'workloads' / name
    assert (base / value['common_rootfs']).resolve() == hook.Path(image['rootfs'])
    assert (base / value['common_bootbinary']).resolve() == hook.Path(image['bootbinary'])
    assert not hook.Path(value['common_rootfs']).is_absolute()
    (tmp_path / 'bootbinary').write_bytes(b'changed')
    try:
        install_descriptor(stage, deploy)
    except ValueError:
        pass
    else:
        raise AssertionError('changed boot binary accepted')
