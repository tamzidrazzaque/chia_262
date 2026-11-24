"""Guest health classification never treats UART silence as a proven failure."""

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from examples.rocket_cost_model.saturn_guest_health import classify
from examples.rocket_cost_model import saturn_guest_health as h


class GuestHealthTests(unittest.TestCase):
    def test_panic_overrides_living_driver(self):
        self.assertIn('FAILED', classify({'matching_driver_pids': [123], 'kernel_panic': True}))

    def test_silence_is_only_warning(self):
        self.assertIn('WARNING', classify({'matching_driver_pids': [123], 'uart_age_seconds': 1200}))
        self.assertNotIn('FAILED', classify({'matching_driver_pids': [123], 'uart_age_seconds': 1200}))

    def test_stale_uart_is_not_attributed_to_unrelated_driver(self):
        self.assertNotIn('FAILED', classify({'matching_driver_pids': [], 'kernel_panic': True}))

    def test_active_without_fatal_evidence(self):
        self.assertIn('driver active', classify({'matching_driver_pids': [123], 'uart_age_seconds': 1}))

    def test_baseline_observation_uses_its_own_stage_and_role(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); baseline = root / 'baseline'; lane = root / 'lane'
            (baseline / '1-scalar').mkdir(parents=True)
            stage = lane / 'staging/auto-3-42'; stage.mkdir(parents=True)
            (baseline / 'progress.json').write_text('{"status":"running","active_role":"1-scalar"}')
            (baseline / '1-scalar/dispatch.json').write_text('{"candidate":"3.42"}')
            (stage / 'runworkload.started.json').write_text('{}')
            plan = {'name': 'job', 'identity': {'role': '1-scalar', 'benchmark': '644.nab_s'}}
            (stage / 'plan.json').write_text(json.dumps(plan)); (lane / 'platform-lock.json').write_text('{}')
            with patch.object(h, 'inspect', return_value={'health': 'active'}) as inspect:
                self.assertEqual(h.baseline_snapshot(baseline, lane)['guest_health']['health'], 'active')
                inspect.assert_called_once_with({}, 'job', 1800)
                diagnosis = root / 'diagnosis.json'
                diagnosis.write_text('{"status":"complete","attempts":[],"active_attempt":null}')
                self.assertEqual(h.baseline_snapshot(baseline, lane, diagnosis)['diagnosis']['status'], 'complete')
                plan['identity']['role'] = '3-saturn-aware'
                (stage / 'plan.json').write_text(json.dumps(plan))
                with self.assertRaises(ValueError): h.baseline_snapshot(baseline, lane)

    def test_campaign_observation_finds_uuid_stage_by_sample_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); run = root / 'run'; lane = root / 'lane'
            (run / 'campaign').mkdir(parents=True)
            stage = lane / 'staging/auto-3-3030-search-17-deadbeef'
            identity_path = stage / 'overlay/root/saturn-spec/stage-identity.json'
            identity_path.parent.mkdir(parents=True)
            expected = {'role': '3-saturn-aware', 'bundle_sha256': 'bundle',
                'sample': 17, 'phase': 'search', 'worker_id': 'worker',
                'platform_sha256': 'platform'}
            identity_path.write_text(json.dumps(expected))
            (stage / 'plan.json').write_text(json.dumps({'name': 'job',
                'identity': {**expected, 'benchmark': '644.nab_s'}}))
            (stage / 'runworkload.started.json').write_text('{}')
            (lane / 'platform-lock.json').parent.mkdir(parents=True, exist_ok=True)
            (lane / 'platform-lock.json').write_text('{"site":"f2"}')
            active = {'artifact': {'role': '3-saturn-aware', 'bundle_sha256': 'bundle'},
                'request': {'sample': 17, 'phase': 'search', 'attempt_id': 'not-the-stage-name'}}
            (run / 'campaign/progress.json').write_text(json.dumps({'status': 'running', 'active': active}))
            request = {'manager_lane': str(lane), 'policy': {'worker_id': 'worker',
                'platform_sha256': 'platform'}}
            (run / 'request.json').write_text(json.dumps(request))
            with patch.object(h, 'inspect', return_value={'health': 'active'}) as inspect:
                result = h.campaign_snapshot(run)
            self.assertEqual(result['guest_health']['health'], 'active')
            inspect.assert_called_once_with({'site': 'f2'}, 'job', 1800)
