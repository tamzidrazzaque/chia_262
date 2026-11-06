"""Read-only acceptance/preflight checks for the platform accepted at f8a923f."""

import json
import re
from pathlib import Path
import subprocess
import time

from .bundle import AGFI, DRIVER_SHA, QUINTUPLET, digest, read_json, sha

SDK = '80b34d3c25aff03353c0b4f2d304bb6067a5011d'
RECORDS = {'saturn-driver-acceptance.json': '4da1edcc654b58822e470a2b952ff0e0c35b8923dcbacf3d00feac0c7f960f3a',
           'saturn-hardware-gate.json': 'e5ea00069faa5602aab13d82cd55d5e071c5e5b5e8b3cb0dbb156670b10a693a'}
PINS = {'.': '19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe', 'sims/firesim': 'b7927ea504c501194eaec3e993c415f2270170f8',
        'generators/saturn': 'dfe75de2a8868d51d42c20612821431a9fcf645e',
        'generators/rocket-chip': '55bcad0f59436de98ea510334121de8546b9e9d7',
        'sims/firesim/platforms/f2/aws-fpga-firesim-f2': SDK}
ARTIFACTS = {'driver', 'driver_bundle', 'base_rootfs', 'base_bootbinary', 'linux_config',
             'busybox_config', 'native_manager_adapter', 'rvv_probe', 'runtime_template', 'readelf', 'objdump'}


def validate_source_status(status, source):
    for line in status.splitlines():
        # marshal install writes runtime descriptors/symlinks, never hardware code.
        if source == 'sims/firesim' and line.startswith('?? ') and re.fullmatch(
                r'deploy/workloads/saturn-spec-[0-9a-f]{24}(?:\.json|/[^\n]+)', line[3:]):
            continue
        raise ValueError('hardware source pin/status changed')


def verify_platform(path):
    site = read_json(path)
    records = Path(__file__).parents[1]
    for name, expected in RECORDS.items():
        if sha(records / name) != expected:
            raise ValueError('accepted platform receipt changed')
    gate = read_json(records / 'saturn-hardware-gate.json')
    for name in ('readelf', 'objdump'):
        if site[name] != site['artifacts'][name]['path']:
            raise ValueError('audit tool identity differs')
    if set(site['artifacts']) != ARTIFACTS:
        raise ValueError('incomplete platform artifact lock')
    for entry in site['artifacts'].values():
        p = Path(entry['path'])
        if not p.is_absolute() or p.is_symlink() or sha(p) != digest(entry['sha256']):
            raise ValueError('platform artifact changed')
    if site['artifacts']['driver']['sha256'] != DRIVER_SHA \
            or site['artifacts']['base_bootbinary']['sha256'] != gate['software_sha256']['linux_bootbinary'] \
            or site['artifacts']['rvv_probe']['sha256'] != gate['guest_binary_sha256']:
        raise ValueError('platform is not the accepted Saturn driver/base/probe')
    if site['artifacts']['native_manager_adapter']['sha256'] != '432b65c8cb23ab9767cded104c62ceab0305cf9abfbee4aec1430899348461e7':
        raise ValueError('native adapter differs from the hardware-tested adapter; scalar adapters forbidden')
    driver = read_json(records / 'saturn-driver-acceptance.json')
    if site['artifacts']['driver_bundle']['sha256'] != driver['driver_bundle_sha256']:
        raise ValueError('driver bundle differs from accepted bundle')
    linux = Path(site['artifacts']['linux_config']['path']).read_text()
    busybox = Path(site['artifacts']['busybox_config']['path']).read_text()
    if 'CONFIG_RISCV_ISA_V=y\n' not in linux or 'CONFIG_RISCV_ISA_V_DEFAULT_ENABLE=y\n' not in linux:
        raise ValueError('Linux base lacks default userspace V support')
    for option in ('TIME', 'SHA256SUM', 'CMP'):
        if 'CONFIG_' + option + '=y\n' not in busybox:
            raise ValueError('Linux base lacks required BusyBox ' + option)
    for relative, expected in PINS.items():
        source = Path(site['chipyard_root']) / relative
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        status = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain',
                                          '--untracked-files=all', '--ignore-submodules=untracked'], text=True)
        if actual != expected:
            raise ValueError('hardware source pin/status changed')
        validate_source_status(status, relative)
    return site


# Executed over existing strict SSH, under the same worker lock as the gate.
REMOTE_CHECK = r'''
import hashlib,json,os,shutil,subprocess,sys,urllib.request
expected=json.loads(sys.argv[1])
free=shutil.disk_usage('/home/ubuntu').free
if free < expected.get('required_free_bytes',0):
    raise RuntimeError('insufficient worker space for the admitted image')
def run(*args): return subprocess.check_output(args,text=True).strip()
if subprocess.run(['pgrep','-x','FireSim-f2'],stdout=subprocess.DEVNULL).returncode == 0:
    raise RuntimeError('worker has an active FPGA driver')
screens=subprocess.run(['screen','-ls'],capture_output=True,text=True)
if 'fsim' in screens.stdout:
    raise RuntimeError('worker has a simulation screen')
if run('git','-C','/home/ubuntu/aws-fpga','rev-parse','HEAD') != expected['sdk']:
    raise RuntimeError('worker SDK differs')
imds='http://169.254.169.254/latest'
token=urllib.request.urlopen(urllib.request.Request(imds+'/api/token',method='PUT',headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'}),timeout=5).read().decode()
instance=urllib.request.urlopen(urllib.request.Request(imds+'/meta-data/instance-id',headers={'X-aws-ec2-metadata-token':token}),timeout=5).read().decode()
if instance != expected['instance']:
    raise RuntimeError('wrong physical worker')
slot=run('sudo','-n','fpga-describe-local-image','-S','0','-H')
if not {expected['agfi'],'loaded','0x10212415'}.issubset(set(slot.split())):
    raise RuntimeError('wrong loaded image/shell')
for name,digest in expected.get('images',{}).items():
    if '/' in name or name in ('.','..'):
        raise RuntimeError('unsafe worker image filename')
    h=hashlib.sha256()
    with open('/home/ubuntu/sim_slot_0/'+name,'rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    if h.hexdigest()!=digest:
        raise RuntimeError('stale worker image')
path='/home/ubuntu/sim_slot_0/FireSim-f2'
if hashlib.sha256(open(path,'rb').read()).hexdigest() != expected['driver']:
    raise RuntimeError('deployed driver differs')
ldd=subprocess.run(['ldd',path],env={**os.environ,'LD_LIBRARY_PATH':'/home/ubuntu/sim_slot_0'},capture_output=True,text=True,check=True).stdout
if 'not found' in ldd:
    raise RuntimeError('missing worker driver dependency')
print(json.dumps({'idle':True,'instance_id':instance,'agfi':expected['agfi'],'driver_sha256':expected['driver'],'shell':'0x10212415','sdk':expected['sdk'],'free_bytes':free}))
'''


def preflight(platform_path):
    site = verify_platform(platform_path)
    # No provision/clear/load/build/run command is present in this preflight.
    import shlex
    expected = json.dumps({'sdk': SDK, 'instance': site['worker_id'], 'agfi': AGFI, 'driver': DRIVER_SHA})
    remote = 'flock -n /home/ubuntu/rocket-runtime.lock python3 - ' + shlex.quote(expected)
    argv = ['ssh', '-i', site['ssh_key'], '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + site['known_hosts'], '-o', 'ConnectTimeout=15',
            'ubuntu@' + site['worker_ip'], remote]
    result = subprocess.run(argv, input=REMOTE_CHECK, text=True, capture_output=True, check=True, timeout=60)
    worker = json.loads(result.stdout)
    observed = {'idle': True, 'instance_id': site['worker_id'], 'agfi': AGFI,
                'driver_sha256': DRIVER_SHA, 'shell': '0x10212415', 'sdk': SDK}
    if any(worker.get(key) != value for key, value in observed.items()):
        raise ValueError('incomplete live worker preflight')
    return {'schema_version': 1, 'checked_at': time.time(), 'expires_after_seconds': 300,
            'platform_sha256': sha(platform_path), 'worker': worker,
            'hardware_gate_sha256': RECORDS['saturn-hardware-gate.json'], 'read_only': True,
            'reservation_held_after_check': False}
