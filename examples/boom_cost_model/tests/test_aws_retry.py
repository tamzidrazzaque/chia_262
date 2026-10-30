import subprocess

import pytest

from examples.boom_cost_model import optimize


def test_transport_retry_is_bounded_and_preserves_command(monkeypatch):
    calls, sleeps = [], []
    def invoke(command, **kwargs):
        calls.append(command)
        if len(calls) < 3:
            raise subprocess.CalledProcessError(255, command, stderr='Could not connect to the endpoint URL')
        return '{"ok": true}'
    monkeypatch.setattr(optimize.subprocess, "check_output", invoke)
    monkeypatch.setattr(optimize.time, "sleep", sleeps.append)
    assert optimize.aws({"aws_profile": "profile", "region": "region"}, "sts", "get-caller-identity") == {"ok": True}
    assert len(calls) == 3 and all(c == calls[0] for c in calls)
    assert sleeps == [1, 2]


def test_authentication_error_is_not_retried(monkeypatch):
    def invoke(command, **kwargs):
        raise subprocess.CalledProcessError(255, command, stderr="Your session has expired")
    monkeypatch.setattr(optimize.subprocess, "check_output", invoke)
    monkeypatch.setattr(optimize.time, "sleep", lambda _: pytest.fail("auth must not retry"))
    with pytest.raises(subprocess.CalledProcessError):
        optimize.aws({"aws_profile": "profile", "region": "region"}, "sts")
