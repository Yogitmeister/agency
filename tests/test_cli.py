import json

import pytest

from agency_pty import cli, ledger


def test_supervised_session_cannot_claim_operator_override(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_HOME", str(tmp_path))
    monkeypatch.setenv("AGENCY_SESSION_ID", "peer")
    ledger.register_session(
        "peer",
        name="peer",
        parent_id=None,
        supervisor_pid=10,
        child_pid=11,
        policy="context",
        argv=["claude"],
    )
    ledger.register_session(
        "target",
        name="target",
        parent_id=None,
        supervisor_pid=12,
        child_pid=13,
        policy="context",
        argv=["claude"],
    )

    with pytest.raises(ledger.LedgerError, match="unavailable inside"):
        cli._cmd_request(
            ["--to", "target", "--command", "/compact", "--operator"]
        )


def test_parent_id_must_match_supervised_caller(monkeypatch):
    monkeypatch.setenv("AGENCY_SESSION_ID", "peer")
    with pytest.raises(ledger.LedgerError, match="under its own session id"):
        cli._cmd_start(["--parent-id", "other", "--", "claude"])


def test_start_loads_named_profile_from_custom_json(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "schema": 1,
                "policies": {
                    "open": {
                        "allow": ["/*"],
                        "deny": ["/exit"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_supervise(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.delenv("AGENCY_SESSION_ID", raising=False)
    monkeypatch.setattr(cli, "supervise", fake_supervise)
    result = cli._cmd_start(
        [
            "--session-id",
            "custom-policy",
            "--policy",
            "open",
            "--policy-file",
            str(policy_file),
            "--",
            "claude",
        ]
    )

    assert result == 0
    assert captured["policy"].name == "open"
    assert captured["policy"].allow == ("/*",)
    assert captured["policy"].deny == ("/exit",)
