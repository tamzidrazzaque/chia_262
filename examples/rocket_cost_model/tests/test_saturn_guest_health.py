"""Guest health classification never treats UART silence as a proven failure."""

import unittest
from examples.rocket_cost_model.saturn_guest_health import classify


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
