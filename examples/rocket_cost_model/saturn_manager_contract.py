"""Bind FireMarshal's installed descriptor to independently admitted images."""

import argparse
import hashlib
import json
from pathlib import Path


def install_descriptor(stage: Path, deploy: Path) -> None:
    plan = json.loads((stage / 'plan.json').read_text())
    image = json.loads((stage / 'image-receipt.json').read_text())
    name = plan['name']
    if Path(name).name != name or not name.startswith('saturn-spec-'):
        raise ValueError('unsafe workload name')
    descriptor = deploy / 'workloads' / (name + '.json')
    value = json.loads(descriptor.read_text())
    if value.get('benchmark_name') != name or value.get('workloads'):
        raise ValueError('unexpected installed descriptor')
    if image['image_id'] != plan['image_id']:
        raise ValueError('wrong image receipt')
    for key, field in [('common_rootfs', 'rootfs'), ('common_bootbinary', 'bootbinary')]:
        source = Path(image[field]).resolve()
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != image[field + '_sha256']:
            raise ValueError('admitted image changed')
        value[key] = str(source)
    descriptor.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install-descriptor'])
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--deploy', type=Path, required=True)
    args = parser.parse_args()
    install_descriptor(args.stage, args.deploy)


if __name__ == '__main__':
    main()
