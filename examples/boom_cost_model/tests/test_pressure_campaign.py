import json
import threading
from types import SimpleNamespace

import pytest

from examples.boom_cost_model import focused_campaign as campaign, pressure_proposals


def test_pressure_mode_uses_policy_schema():
    assert campaign.proposal_api({"campaign_kind": "pressure"}) is pressure_proposals
    proposal = pressure_proposals.seed_profiles()[1]
    pressure_proposals.validate(proposal)
    with pytest.raises(ValueError):
        pressure_proposals.validate({**proposal, "costs": {**proposal["costs"], "memory_cost": 2}})


def test_explicit_opus_effort_is_forwarded_and_recorded(tmp_path,monkeypatch):
    value=pressure_proposals.seed_profiles()[0]
    class LLM:
        def __init__(self,**kwargs):
            assert kwargs['model']=='claude-opus-5-5'
            assert kwargs['backend']=='cli'
            assert kwargs['extra_cli_args']==['--tools','','--strict-mcp-config','--effort','xhigh']
            assert not kwargs['dangerously_skip_permissions']
        def prompt(self,prompt,tools):
            assert tools==[]
            return SimpleNamespace(success=True,result=json.dumps(value))
    monkeypatch.setattr(pressure_proposals,'ClaudeCodeLLM',LLM)
    assert pressure_proposals.request_json({'model':'claude-opus-5-5','llm_effort':'xhigh'},
        {'task':'Test bounded profile'},tmp_path,pressure_proposals.validate)==value
    assert json.loads((tmp_path/'llm-settings.json').read_text())['effort']=='xhigh'


def test_invalid_effort_does_not_start_a_model_process(tmp_path,monkeypatch):
    monkeypatch.setattr(pressure_proposals,'ClaudeCodeLLM',lambda **_:pytest.fail('must not launch'))
    with pytest.raises(ValueError,match='effort'):
        pressure_proposals.request_json({'model':'test','llm_effort':'invalid'}, {},tmp_path,lambda p:p)


def test_feedback_preserves_pending_policies_and_static_evidence(tmp_path, monkeypatch):
    value = pressure_proposals.seed_profiles()[1]
    seen = {}
    class LLM:
        def __init__(self, **kwargs):
            assert not kwargs["dangerously_skip_permissions"]
            assert kwargs["extra_cli_args"] == ["--tools", "", "--strict-mcp-config"]
        def prompt(self, prompt, tools):
            assert tools == []
            seen.update(json.loads(prompt))
            return SimpleNamespace(success=True, result=json.dumps(value))
    monkeypatch.setattr(pressure_proposals, "ClaudeCodeLLM", LLM)
    result = pressure_proposals.feedback_proposal({"model": "example", "analysis_evidence": {"moves": 0}},
        [{"index": 4, "proposal": value, "pending": True}], [], tmp_path)
    assert result == value
    assert seen["history"][0]["pending"]
    assert seen["analysis_evidence"]["moves"] == 0
    assert (tmp_path / "prompt.json").is_file() and (tmp_path / "response.txt").is_file()


def test_pressure_followups_wait_for_all_seeds_and_include_pending(tmp_path, monkeypatch):
    release_four = threading.Event()
    seen = []
    class Experiment:
        def __init__(self, config, directory):
            self.config, self.directory, self.hardware = config, directory, {}
    def prepare(config, directory, index=None, proposal=None):
        return {"index": index, "proposal": proposal, "compiler": {"compiler_id": str(index)},
                "code_generation": {"benchmark": str(index)}, "workload": None}
    def measure(ex, prepared, label, **kwargs):
        if prepared["index"] == 4:
            assert release_four.wait(5)
        return {"times": {"648.exchange2_s": 100}}
    def propose(config, history, prior, directory):
        completed = {h["index"] for h in history if h.get("success")}
        assert {0, 1, 2, 3} <= completed
        value = pressure_proposals.seed_profiles()[0]
        value["policy"] = {"pressure_algorithm": 1, "ira_loop_pressure": False,
                           "growth_budget": "default" if not seen else "compact"}
        if seen:
            assert any(h["index"] == 4 and h.get("pending") for h in history)
            release_four.set()
        seen.append(value)
        return value
    monkeypatch.setattr(campaign, "Experiment", Experiment)
    monkeypatch.setattr(campaign, "prepare", prepare)
    monkeypatch.setattr(campaign, "measure", measure)
    monkeypatch.setattr(campaign, "verified_workers", lambda *args: [{"instance_id": "a"}, {"instance_id": "b"}])
    monkeypatch.setattr(campaign, "prior_train_evidence", lambda *args: [])
    monkeypatch.setattr(campaign.signal, "signal", lambda *args: None)
    monkeypatch.setattr(pressure_proposals, "feedback_proposal", propose)
    campaign.run({"benchmarks": ["648.exchange2_s"], "campaign_kind": "pressure", "campaign_budget": 6,
                  "confirm_repeats": 3, "min_improvement": 0.01, "final_ref": False}, tmp_path)
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["complete"] and len(result["history"]) == 6 and len(seen) == 2


def test_pressure_winner_is_confirmed_even_when_reference_is_disabled(tmp_path, monkeypatch):
    labels = []
    class Experiment:
        def __init__(self, config, directory):
            self.config, self.directory, self.hardware = config, directory, {}
    def prepare(config, directory, index=None, proposal=None):
        return {"index": index, "proposal": proposal, "compiler": {"compiler_id": str(index)},
                "code_generation": {"benchmark": str(index)}, "workload": None}
    def measure(ex, item, label, **kwargs):
        labels.append((label, kwargs.get("repeats")))
        return {"times": {"648.exchange2_s": 90 if item["index"] == 1 else 100}}
    monkeypatch.setattr(campaign, "Experiment", Experiment)
    monkeypatch.setattr(campaign, "prepare", prepare)
    monkeypatch.setattr(campaign, "measure", measure)
    monkeypatch.setattr(campaign, "verified_workers", lambda *args: [{"instance_id": "a"}, {"instance_id": "b"}])
    monkeypatch.setattr(campaign, "prior_train_evidence", lambda *args: [])
    monkeypatch.setattr(campaign.signal, "signal", lambda *args: None)
    campaign.run({"benchmarks": ["648.exchange2_s"], "campaign_kind": "pressure", "campaign_budget": 2,
                  "confirm_repeats": 3, "min_improvement": 0.01, "final_ref": False}, tmp_path)
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["train_confirmation_checked"] and not result["reference_checked"]
    assert result["confirmed_train_speedup"] > 1.1
    assert ("confirm-baseline", 3) in labels and ("confirm-winner", 3) in labels
    assert not any("heldout" in name for name, _ in labels)
