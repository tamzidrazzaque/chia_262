"""Sparse transfer behavior is tested with real files, without a live FPGA."""
import ast
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from chia.firesim import manager_node


def helpers(local):
    tree=ast.parse(manager_node._MANAGER)
    names={'sparse_slot_copy','put_in_home','get_from_home','rsync_in_home'}
    body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    namespace={'local':local,'re':re}
    exec(compile(ast.Module(body=body,type_ignores=[]),'<manager helpers>','exec'),namespace)
    return namespace


@pytest.mark.parametrize('separator',['/','//'])
def test_pinned_bulk_slot_copy_preserves_sparse_extents(separator):
    command=f'cp -r /home/ubuntu/sim_slot_0/rsyncdir{separator}* /home/ubuntu/sim_slot_0/'
    assert helpers(None)['sparse_slot_copy'](command)==command.replace('cp -r ','cp -r --sparse=always ',1)


@pytest.mark.parametrize('command',['rm -rf /unrelated',
    'cp -r /other/rsyncdir/* /other/',
    'cp -r /home/ubuntu/sim_slot_0/rsyncdir/* /home/ubuntu/sim_slot_1/'])
def test_sparse_policy_does_not_rewrite_unrelated_commands(command):
    assert helpers(None)['sparse_slot_copy'](command)==command


@pytest.mark.parametrize('method',['put_in_home','get_from_home','rsync_in_home'])
def test_real_transfer_keeps_content_without_allocating_zero_image(method,tmp_path):
    if method=='rsync_in_home' and not shutil.which('rsync'):
        pytest.skip('rsync not installed')
    source=tmp_path/'source.img';destination=tmp_path/'destination.img'
    source.write_bytes(b'header'+bytes(16*1024*1024))
    def local(command,**kw):
        return subprocess.run(command,shell=True,check=True,capture_output=True)
    fn=helpers(local)[method]
    if method=='rsync_in_home':fn(str(destination),str(source))
    else:fn(str(source),str(destination))
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(destination.read_bytes()).digest()
    assert destination.stat().st_size==source.stat().st_size
    assert destination.stat().st_blocks*512 < destination.stat().st_size//4


@pytest.mark.parametrize('task,mtime,expected',[('infrasetup',101,''),
    ('runworkload',50,''),('runworkload',101,'new partial UART')])
def test_failed_setup_never_misattributes_a_previous_uart(monkeypatch,task,mtime,expected):
    for name in ['render_runtime_config','render_hwdb','report']:
        monkeypatch.setattr(manager_node,name,lambda *a,**k:None)
    monkeypatch.setattr(manager_node,'stage_workload',lambda *a:'new-job')
    monkeypatch.setattr(manager_node.time,'time',lambda:100)
    slot=SimpleNamespace(exists=lambda:True,stat=lambda:SimpleNamespace(st_mtime=mtime),
        read_text=lambda **kw:'new partial UART')
    monkeypatch.setattr(manager_node,'Path',lambda *_:slot)
    node=manager_node.FireSimManagerNode.__new__(manager_node.FireSimManagerNode)
    node.logger=SimpleNamespace(info=lambda *_:None)
    node._firesim=lambda phase:((1,'failed') if phase==task else (0,'ok'))
    result=node._run('host',None,None,None)
    assert not result.success and result.benchmark_name=='new-job'
    assert result.uartlog==expected
