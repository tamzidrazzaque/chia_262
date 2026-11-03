from copy import deepcopy
import json
import threading

import pytest

from examples.boom_cost_model import focused_campaign as campaign
from examples.boom_cost_model.adaptive_proposals import AdaptiveProposals
from examples.boom_cost_model.tests.test_autopilot import config


def test_adaptive_feedback_uses_completed_control_and_marks_running_seed_pending(tmp_path,monkeypatch):
    cfg = config()
    seed = deepcopy(cfg['adaptive_seeds'][0])
    seed['costs']['branch_cost'] = 3
    cfg.update(adaptive_seeds=[*cfg['adaptive_seeds'],seed],campaign_budget=4)
    release = threading.Event()
    seen = []
    class Experiment:
        def __init__(self,config,directory):
            self.config,self.directory,self.hardware = config,directory,{}
            directory.mkdir(parents=True,exist_ok=True)
    def prepare(config,directory,index=None,proposal=None):
        return {'index':index,'proposal':proposal,'compiler':{'compiler_id':str(index)},
            'code_generation':{'benchmark':str(index)},'workload':None}
    def measure(ex,item,label,**kwargs):
        if item['index'] == 2:
            assert release.wait(10), 'feedback must not wait for the final seed'
        return {'times':{'641.leela_s':100}}
    def feedback(self,config,history,prior,directory):
        completed={h['index'] for h in history if h.get('success')}
        assert {0,1} <= completed and 2 not in completed
        assert any(h['index'] == 2 and h.get('pending') and 'train_times' not in h for h in history)
        seen.append(history)
        release.set()
        result=deepcopy(self.seed_profiles()[0]);result['costs']['branch_cost']=2
        return result
    monkeypatch.setattr(campaign,'Experiment',Experiment)
    monkeypatch.setattr(campaign,'prepare',prepare)
    monkeypatch.setattr(campaign,'measure',measure)
    monkeypatch.setattr(campaign,'verified_workers',lambda *_:[{'instance_id':'a'},{'instance_id':'b'}])
    monkeypatch.setattr(campaign,'prior_train_evidence',lambda *_:[])
    monkeypatch.setattr(campaign.signal,'signal',lambda *_:None)
    monkeypatch.setattr(AdaptiveProposals,'feedback_proposal',feedback)
    campaign.run(cfg,tmp_path)
    assert len(seen)==1
    assert json.loads((tmp_path/'scheduling.json').read_text())['feedback_min_completed']==2
    assert json.loads((tmp_path/'result.json').read_text())['complete']


@pytest.mark.parametrize('value',[True,1,9])
def test_early_feedback_minimum_is_bounded(value):
    with pytest.raises(ValueError,match='early feedback'):
        campaign.validate_config({**config(),'feedback_min_completed':value})
