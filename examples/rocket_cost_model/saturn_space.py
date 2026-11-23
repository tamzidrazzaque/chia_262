"""Reclaim zero blocks from completed images while preserving every byte."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

from examples.rocket_cost_model.saturn_spec.execution import ssh_args
from examples.rocket_cost_model.saturn_spec.staging import verify_stage


SCRIPT = r'''
import hashlib,json,os,stat,subprocess,sys
from pathlib import Path
request=json.loads(sys.argv[1])
if 'FireSim-f2' in subprocess.check_output(['ps','-eo','comm'],text=True).splitlines():
    raise RuntimeError('simulation is active; refuse image maintenance')
records=[]
for name in request['paths']:
    path=Path(name)
    root=Path(request['root']).resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.name.endswith('.img'):
        raise ValueError('unsafe completed image path')
    before=path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
        raise ValueError('completed image must be an unshared regular file')
    if str(path) in Path('/proc/mounts').read_text():
        raise RuntimeError('image is mounted')
    if subprocess.check_output(['losetup','-j',str(path)],text=True).strip():
        raise RuntimeError('image has an attached loop device')
    def digest():
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                h.update(chunk)
        return h.hexdigest()
    checksum=digest()
    subprocess.run(['fallocate','--dig-holes',str(path)],check=True)
    after=path.stat()
    if digest()!=checksum or after.st_size!=before.st_size or after.st_ino!=before.st_ino:
        raise RuntimeError('image identity changed during compaction')
    records.append({'file':path.name,'sha256':checksum,
                    'reclaimed_bytes':max(0,(before.st_blocks-after.st_blocks)*512)})
print(json.dumps({'status':'preserved','images':records}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    plan = verify_stage(args.stage)
    receipt = json.loads((args.stage / 'collection/result.json').read_text())
    if receipt.get('status') != 'correct' or receipt.get('image_id') != plan['image_id']:
        raise ValueError('completed validated collection required before maintenance')
    image = json.loads((args.stage / 'image-receipt.json').read_text())
    rootfs = Path(image['rootfs']).resolve()
    if rootfs.name != plan['name'] + '.img':
        raise ValueError('not the completed per-run rootfs')
    manager = subprocess.check_output([sys.executable, '-c', SCRIPT,
        json.dumps({'root': str(rootfs.parent), 'paths': [str(rootfs)]})], text=True)
    site = json.loads(Path(plan['platform']).read_text())
    slot = '/home/ubuntu/sim_slot_0'
    name = plan['name'] + '0-' + rootfs.name
    request = {'root': slot, 'paths': [slot + '/' + name, slot + '/rsyncdir/' + name]}
    command = 'flock -n /home/ubuntu/rocket-runtime.lock python3 -c ' + shlex.quote(SCRIPT) + ' ' + shlex.quote(json.dumps(request))
    worker = subprocess.check_output(ssh_args(site) + [command], text=True)
    print(json.dumps({'manager': json.loads(manager), 'worker': json.loads(worker)}))


if __name__ == '__main__':
    main()
