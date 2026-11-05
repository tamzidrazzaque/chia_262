import json
import fcntl
from types import SimpleNamespace

import pytest

from examples.boom_cost_model import watchdog


@pytest.mark.parametrize('overrides,expected',[
    ({'stopped':True},'stopped'),
    ({'state':{'stop_requested':True}},'stopped'),
    ({'state':{'phase':'stopped'}},'stopped'),
    ({'supervisors':[1]},'supervised'),
    ({'supervisors':[1],'state':{'phase':'waiting-for-preflight'}},'supervised-preflight-blocked'),
    ({'controllers':[2]},'preserve-active-work'),
    ({'drivers':{'worker':'active'}},'preserve-active-work'),
    ({'complete':False},'investigate-incomplete-run'),
    ({'drivers':{'worker':'unknown'}},'connectivity-unknown'),
    ({'drivers':{}},'connectivity-unknown'),
    ({},'verify-before-restart'),
])
def test_recovery_gate_preserves_active_failed_and_stopped_work(overrides,expected):
    values={'state':{},'complete':True,'supervisors':[],'controllers':[],
        'drivers':{'worker':'idle'},'stopped':False}
    values.update(overrides)
    assert watchdog.recovery_action(**values)==expected


def test_process_detection_uses_exact_module_root_and_owner(tmp_path):
    root=tmp_path/'experiment';root.mkdir();proc=tmp_path/'proc';proc.mkdir()
    def put(pid,argv):
        p=proc/str(pid);p.mkdir();(p/'cmdline').write_bytes(('\0'.join(argv)+'\0').encode())
    put(1,['python','-m','examples.boom_cost_model.autopilot','--directory',str(root)])
    put(2,['python','-m','examples.boom_cost_model.focused_campaign','--run-dir',str(root/'round/run')])
    put(3,['bash','-c','examples.boom_cost_model.autopilot --directory '+str(root)])
    put(4,['python','-m','examples.boom_cost_model.autopilot','--directory',str(tmp_path/'other')])
    put(5,['python','-m','examples.boom_cost_model.reference_check',
        '--source',str(root/'round/run'),'--run-dir',str(tmp_path/'external-reference')])
    put(6,['python','-m','examples.boom_cost_model.run_probes','--run-dir',str(tmp_path/'external-diagnostic')])
    put(7,['python','-m','examples.boom_cost_model.reference_check','--source',str(tmp_path/'other')])
    supervisors,controllers=watchdog.loop_processes(root,proc,owned_pids=[6])
    assert supervisors==[1] and sorted(controllers)==[2,5,6]


@pytest.mark.parametrize('code,expected',[(0,'active'),(1,'idle'),(255,'unknown')])
def test_ssh_failure_is_never_idle_and_host_verification_stays_enabled(monkeypatch,code,expected):
    def run(argv,**kwargs):
        assert '-o' in argv and 'StrictHostKeyChecking=yes' in argv and 'BatchMode=yes' in argv
        assert argv[-1]=='pgrep -x FireSim-f2'
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(watchdog.subprocess,'run',run)
    assert watchdog.driver_states({'fpga_workers':[{'ssh_alias':'test-f2'}]})=={'test-f2':expected}


def fixture(tmp_path,monkeypatch,complete=True):
    current=tmp_path/'round-001/run';current.mkdir(parents=True)
    campaign={'fpga_workers':[{'ssh_alias':'test-f2'}]}
    (current.parent/'config.json').write_text(json.dumps(campaign))
    (tmp_path/'settings.json').write_text('{}')
    (tmp_path/'state.json').write_text(json.dumps({'phase':'blocked','current':str(current),'round':1,'failure':'preserve this error'}))
    if complete:(current/'result.json').write_text('{"complete":true}')
    monkeypatch.setattr(watchdog,'loop_processes',lambda *_:([],[]))
    monkeypatch.setattr(watchdog,'driver_states',lambda *_:{'test-f2':'idle'})
    monkeypatch.setattr(watchdog,'authentication',lambda *_:'verified')
    monkeypatch.setattr(watchdog.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    return {'root':str(tmp_path),'tmux_session':'chia'}


def test_incomplete_run_never_launches_a_retry(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch,complete=False)
    monkeypatch.setattr(watchdog,'start_supervisor',lambda *_:pytest.fail('cannot retry a failed benchmark'))
    assert watchdog.check(config)['action']=='investigate-incomplete-run'
    assert json.loads((tmp_path/'state.json').read_text())['failure']=='preserve this error'


def test_recovery_requires_existing_review_preflight_and_occurs_once(tmp_path,monkeypatch):
    from examples.boom_cost_model import autopilot
    config=fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(autopilot,'review',lambda *_:calls.append('review'))
    monkeypatch.setattr(autopilot,'dispatch_ready',lambda *_:calls.append('preflight'))
    monkeypatch.setattr(watchdog,'start_supervisor',lambda *_:calls.append('start'))
    assert watchdog.check(config)['action']=='supervisor-restarted'
    assert calls==['review','preflight','start']
    snapshots=list((tmp_path/'monitor').glob('state-before-recovery-*.json'))
    assert len(snapshots)==1 and json.loads(snapshots[0].read_text())['failure']=='preserve this error'
    assert watchdog.check(config)['action']=='repeated-failure-needs-investigation'
    assert calls.count('start')==1


def test_finality_failure_and_wrong_identity_preserve_state(tmp_path,monkeypatch):
    from examples.boom_cost_model import autopilot
    config=fixture(tmp_path,monkeypatch)
    original=(tmp_path/'state.json').read_bytes()
    monkeypatch.setattr(watchdog,'start_supervisor',lambda *_:pytest.fail('unsafe restart'))
    def refuse(*_):raise ValueError('later failure invalidates completion')
    monkeypatch.setattr(autopilot,'review',refuse)
    assert watchdog.check(config)['action']=='preflight-or-finality-check-failed'
    assert (tmp_path/'state.json').read_bytes()==original
    monkeypatch.setattr(watchdog,'authentication',lambda *_:'wrong-identity')
    assert watchdog.check(config,True)['action']=='authentication-required'
    assert (tmp_path/'state.json').read_bytes()==original


def test_monitor_stop_control_prevents_network_checks_and_recovery(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch)
    (tmp_path/'monitor').mkdir();(tmp_path/'monitor/STOP').touch()
    (tmp_path/'monitor/status.json').write_text(json.dumps({'authentication':'expired',
        'drivers':{'test-f2':'unknown'}}))
    (tmp_path/'monitor/attention.json').write_text('{}')
    monkeypatch.setattr(watchdog,'driver_states',lambda *_:pytest.fail('monitor stopped'))
    monkeypatch.setattr(watchdog,'authentication',lambda *_:pytest.fail('monitor stopped'))
    monkeypatch.setattr(watchdog.subprocess,'run',lambda *_args,**_kwargs:pytest.fail('no notifications while stopped'))
    assert watchdog.check(config)['action']=='stopped'
    assert not (tmp_path/'monitor/attention.json').exists()


def test_healthy_ticks_do_not_repeat_remote_audits_before_30_minutes(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch)
    state=json.loads((tmp_path/'state.json').read_text());state['phase']='running'
    (tmp_path/'state.json').write_text(json.dumps(state))
    monkeypatch.setattr(watchdog,'loop_processes',lambda *_:([1],[]))
    first=watchdog.check(config,True)
    monkeypatch.setattr(watchdog,'driver_states',lambda *_:pytest.fail('audit not due'))
    monkeypatch.setattr(watchdog,'authentication',lambda *_:pytest.fail('audit not due'))
    second=watchdog.check(config)
    assert first['last_audit']==second['last_audit']
    assert len((tmp_path/'monitor/audits.jsonl').read_text().splitlines())==1


@pytest.mark.parametrize('code,stdout,stderr,expected',[
    (0,'{"Arn":"arn:aws:iam::000000000000:user/test"}','','verified'),
    (0,'{"Arn":"arn:aws:iam::000000000000:root"}','','wrong-identity'),
    (1,'','Your session has expired.','expired'),
    (0,'invalid JSON','','unknown'),
])
def test_authentication_checks_identity_without_exporting_credentials(monkeypatch,code,stdout,stderr,expected):
    def run(argv,**kwargs):
        assert 'get-caller-identity' in argv and not any('credentials' in x for x in argv)
        return SimpleNamespace(returncode=code,stdout=stdout,stderr=stderr)
    monkeypatch.setattr(watchdog.subprocess,'run',run)
    assert watchdog.authentication({'aws_profile':'test','region':'us-east-1',
        'aws_account':'000000000000','iam_user':'test'})==expected


def test_restart_preserves_existing_tmux_windows_and_quotes_config(tmp_path,monkeypatch):
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(watchdog.subprocess,'run',run)
    config={'tmux_session':'chia','python':'/tool/python','initial_run':'/work/initial',
        'root':'/work/root','environment':'/work/env with spaces.sh'}
    watchdog.start_supervisor(config,tmp_path)
    assert [c[1] for c in calls]==['has-session','new-window']
    assert '--initial-run' in calls[-1][-1] and '/work/initial' in calls[-1][-1]
    assert not any('send-keys' in c or 'respawn-window' in c for c in calls)
    with pytest.raises(ValueError,match='tmux session'):
        watchdog.start_supervisor({**config,'tmux_session':'unsafe;command'},tmp_path)


def test_overlapping_cron_check_does_not_inspect_or_restart_experiment(tmp_path):
    directory=tmp_path/'monitor';directory.mkdir()
    with (directory/'watchdog.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert watchdog.check({'root':str(tmp_path)})=={'action':'previous-check-active'}
