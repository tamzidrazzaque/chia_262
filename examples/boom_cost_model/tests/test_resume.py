import pytest

from examples.boom_cost_model.optimize import resumed_proposal, save


def test_resumes_saved_proposal_only_with_matching_prompt_and_compiler(tmp_path):
    prompt = {"history": [{"index": 0, "speedup": 0.99}], "hardware": "pinned"}
    save(tmp_path / "claude" / "prompt-003.json", prompt)
    response = '{"costs": {"memory_cost": 5}}'
    (tmp_path / "claude" / "response-003.txt").write_text(response)
    assert resumed_proposal(tmp_path, 3, prompt) is None

    save(tmp_path / "candidate-003" / "compiler.json", {"compiler_id": "fixed"})
    assert resumed_proposal(tmp_path, 3, prompt) == response
    with pytest.raises(ValueError, match="prompt differs"):
        resumed_proposal(tmp_path, 3, {"history": [], "hardware": "pinned"})


def test_rejects_empty_saved_response(tmp_path):
    prompt = {"hardware": "pinned"}
    save(tmp_path / "claude" / "prompt-003.json", prompt)
    save(tmp_path / "candidate-003" / "compiler.json", {"compiler_id": "fixed"})
    (tmp_path / "claude" / "response-003.txt").write_text(" \n")
    with pytest.raises(ValueError, match="empty"):
        resumed_proposal(tmp_path, 3, prompt)
