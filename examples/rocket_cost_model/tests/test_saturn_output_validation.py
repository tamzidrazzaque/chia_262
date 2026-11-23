"""Output policy fixtures contain no SPEC data."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from examples.rocket_cost_model.saturn_spec import output_validation as v


class OutputValidationTests(unittest.TestCase):
    def test_conservative_float_tolerance(self):
        report = v.compare_nab('energy -100.00\nsteps 1000\n', 'energy -100.01\nsteps 1000\n')
        self.assertEqual(report['different_numeric_values'], 1)
        self.assertEqual(report['numeric_tokens'], 2)
        self.assertEqual(report['skipped_differences'], 0)

    def test_fail_closed_for_missing_extra_text_integer_and_bad_numbers(self):
        for actual in ('', 'energy 1.00', 'energy 1.02\nsteps 1000\n',
                       'energy nan\nsteps 1000\n', 'energy inf\nsteps 1000\n',
                       'energy 1.001\nsteps 1001\n', 'energy 1.001\nsteps 1000\nextra',
                       'energy 1e99999\nsteps 1000\n'):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                v.compare_nab('energy 1.00\nsteps 1000\n', actual)

    def test_boundary_zero_and_no_skip_allowance(self):
        v.compare_nab('value 1.0\n', 'value 1.01\n')
        for ref, got in [('value 0.0\n', 'value 0.0001\n'),
                         ('value 1.0\n', 'value 1.010001\n')]:
            with self.assertRaises(ValueError):
                v.compare_nab(ref, got)

    def test_policy_is_bound_to_benchmark_size_filename_and_reference(self):
        with TemporaryDirectory() as directory:
            ref, got = (Path(directory) / name for name in ('reference', 'actual'))
            ref.write_text('value 1.0\n'); got.write_text('value 1.001\n')
            m = {'benchmark': '644.nab_s', 'size': 'test',
                 'expected_outputs': {'hkrdenq.out': 'reference'},
                 'files_sha256': {'reference': v.sha(ref)}}
            with patch.object(v, 'NAB_TEST_REFERENCE_SHA', v.sha(ref)):
                self.assertIn('relative_tolerance', v.validate_output(m, 'hkrdenq.out', ref, got))
                for key, wrong in [('benchmark', '605.mcf_s'), ('size', 'train')]:
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        v.validate_output({**m, key: wrong}, 'hkrdenq.out', ref, got)
            with self.assertRaises(ValueError):
                v.validate_output(m, 'hkrdenq.out', ref, got)
            got.write_bytes(ref.read_bytes())
            self.assertEqual(v.validate_output(m, 'hkrdenq.out', ref, got)['validator'], 'exact-output-sha256')
            ref.write_text('tampered\n')
            with self.assertRaises(ValueError):
                v.validate_output(m, 'hkrdenq.out', ref, got)
