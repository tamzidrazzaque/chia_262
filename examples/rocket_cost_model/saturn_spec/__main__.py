"""SPEC execution-lane preparation only. No guest build or hardware launch command."""

import argparse
import json
from pathlib import Path

from .bundle import intake
from .platform import preflight, verify_platform
from .results import collect
from .staging import stage, verify_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('intake')
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--verified-root', required=True, type=Path)
    p.add_argument('--platform', required=True, type=Path)
    p = sub.add_parser('stage')
    for name in ('snapshot', 'platform', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--phase', required=True, choices=('baseline', 'search', 'confirmation', 'holdout'))
    p.add_argument('--sample', required=True, type=int)
    p.add_argument('--scratch-mib', type=int, default=1024)
    p = sub.add_parser('preflight')
    p.add_argument('--platform', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p = sub.add_parser('verify-image')
    for name in ('stage', 'rootfs', 'bootbinary', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    p = sub.add_parser('collect')
    for name in ('stage', 'image', 'completion', 'preflight', 'collected', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    a = parser.parse_args()
    if a.command == 'intake':
        site = verify_platform(a.platform)
        print(intake(a.bundle, a.verified_root, a.manifest_sha256, site['readelf'], site['objdump']))
    elif a.command == 'stage':
        print(json.dumps(stage(a.snapshot, a.platform, a.out, a.phase, a.sample, a.scratch_mib), indent=2))
    elif a.command == 'preflight':
        value = preflight(a.platform)
        with a.out.open('x') as f:
            f.write(json.dumps(value, indent=2) + '\n')
        print(a.out)
    elif a.command == 'verify-image':
        value = verify_image(a.stage, a.rootfs, a.bootbinary)
        with a.out.open('x') as f:
            f.write(json.dumps(value, indent=2) + '\n')
        print(a.out)
    else:
        print(json.dumps(collect(a.stage, a.image, a.completion, a.preflight, a.collected, a.out), indent=2))


if __name__ == '__main__':
    main()
