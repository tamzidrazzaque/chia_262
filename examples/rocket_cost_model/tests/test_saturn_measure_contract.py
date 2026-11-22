"""Transport contract checks without credentials, SPEC or hardware."""

import hashlib
import json
from unittest.mock import patch, MagicMock

from examples.rocket_cost_model import saturn_measure_hook as hook


def test_transport_contract(tmp_path):
    bundle = tmp_path / 'bundle/3-saturn-aware'
    bundle.mkdir(parents=True)
    (bundle / 'manifest.json').write_text('{}')
    digest = hashlib.sha256(b'{}').hexdigest()
    receipt = {'status': 'correct', 'identity': {'bundle_sha256': digest}}
    calls = []

    def ssh(host, key, command, capture=False):
        calls.append(command)
        return json.dumps(receipt) if capture else ''

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
