"""Conservative output policies; licensed references remain outside Git."""

from decimal import Decimal, localcontext
from pathlib import Path
import re

from .bundle import sha

NAB_TEST_REFERENCE_SHA = '2d580a95e2e596f2e06485149e9d91880bf47ded5a5495a366a80d4cea2a9afd'
NUMBER = re.compile(r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?')


def compare_nab(reference: str, actual: str) -> dict:
    """Require exact structure and every float within NAB's 1% relative limit.

    This intentionally accepts a subset of the official SPEC comparison:
    no whitespace relaxation, no integer tolerance and no skipped failures
    (the official NAB setting permits two relative-tolerance exceptions).
    It is not a replacement implementation of specdiff.
    """
    expected, produced = NUMBER.findall(reference), NUMBER.findall(actual)
    if not expected or NUMBER.split(reference) != NUMBER.split(actual):
        raise ValueError('NAB output structure or numeric token count mismatch')
    maximum = Decimal(0)
    changed = 0
    with localcontext() as context:
        context.prec = 80
        for ref, got in zip(expected, produced):
            if max(len(ref), len(got)) > 128:
                raise ValueError('NAB numeric token exceeds supported size')
            a, b = Decimal(ref.replace('D', 'E').replace('d', 'e')), Decimal(got.replace('D', 'E').replace('d', 'e'))
            if not a.is_finite() or not b.is_finite() or any(abs(x.adjusted()) > 1000 for x in (a, b)):
                raise ValueError('NAB nonfinite or unsupported numeric value')
            if a == b:
                continue
            if not any(c in ref for c in '.eEdD'):
                raise ValueError('NAB integer output mismatch')
            if a == 0 or abs(a - b) > abs(a) * Decimal('0.01'):
                raise ValueError('NAB output exceeds official relative tolerance')
            changed += 1
            maximum = max(maximum, abs(a - b) / abs(a))
    return {'validator': 'nab-reltol-0.01-strict-structure-v1',
            'relative_tolerance': '0.01', 'skipped_differences': 0,
            'numeric_tokens': len(expected), 'different_numeric_values': changed,
            'max_relative_difference': str(maximum)}


def validate_output(manifest: dict, name: str, reference: Path, actual: Path) -> dict:
    """Apply tolerance only to the pinned official NAB test reference."""
    reference_sha, actual_sha = sha(reference), sha(actual)
    source = manifest['expected_outputs'][name]
    if reference_sha != manifest['files_sha256'][source]:
        raise ValueError('output reference changed')
    if reference_sha == actual_sha:
        return {'validator': 'exact-output-sha256', 'sha256': actual_sha}
    if (manifest['benchmark'], manifest['size'], name, reference_sha) != (
            '644.nab_s', 'test', 'hkrdenq.out', NAB_TEST_REFERENCE_SHA):
        raise ValueError('SPEC exact expected-output mismatch')
    report = compare_nab(reference.read_text(), actual.read_text())
    return {**report, 'reference_sha256': reference_sha, 'sha256': actual_sha}
