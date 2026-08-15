import json

import pytest

from agency_pty.policy import CommandPolicy, PolicyError, normalize_command, parse_policy


def test_context_policy_accepts_context_and_diagnostics():
    policy = parse_policy("context")
    for command in ("/compact keep state", "/context all", "/status", "/usage"):
        assert policy.accepts(command)[0]


def test_context_policy_refuses_runtime_changes():
    accepted, detail = parse_policy("context").accepts("/model opus")
    assert not accepted
    assert "context policy" in detail


def test_self_manage_policy_accepts_runtime_adaptation():
    policy = parse_policy("self-manage")
    for command in ("/effort high", "/model sonnet", "/fast on", "/plan inspect auth", "/exit"):
        assert policy.accepts(command)[0]


def test_self_manage_policy_keeps_operator_settings_out():
    accepted, detail = parse_policy("self-manage").accepts("/permissions")
    assert not accepted
    assert "self-manage policy" in detail


def test_all_slash_accepts_local_commands_but_not_prompts():
    policy = parse_policy("all-slash")
    assert policy.accepts("/permissions")[0]
    assert not policy.accepts("please compact")[0]


def test_multiline_command_is_rejected():
    try:
        normalize_command("/compact\n/exit")
    except PolicyError as exc:
        assert "one line" in str(exc)
    else:
        raise AssertionError("multiline command was accepted")


def test_terminal_control_characters_are_rejected():
    for command in (
        "/compact\x1b[A",
        "/model\tsonnet",
        "/exit\x7f",
        "/compact \u202ehidden",
        "/compact zero\u200bwidth",
    ):
        accepted, detail = parse_policy("all-slash").accepts(command)
        assert not accepted
        assert "control characters" in detail


def test_suffix_star_includes_arguments_but_not_other_command_names():
    policy = parse_policy("self-manage")
    assert policy.accepts("/model")[0]
    assert policy.accepts("/model sonnet max")[0]
    assert not policy.accepts("/model-other sonnet")[0]


def test_deny_rules_win_over_allow_rules():
    policy = CommandPolicy(
        name="custom",
        allow=("/*",),
        deny=("/permissions*",),
        source="test",
    )
    assert policy.accepts("/model opus")[0]
    accepted, detail = policy.accepts("/permissions allow all")
    assert not accepted
    assert "deny rule" in detail


def test_custom_json_can_define_new_policy(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
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
    policy = parse_policy("open", path)
    assert policy.accepts("/model anything")[0]
    assert not policy.accepts("/exit")[0]
    assert policy.source == str(path.resolve())


def test_invalid_policy_pattern_is_rejected(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "policies": {
                    "bad": {
                        "allow": ["/model*oops"],
                        "deny": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="invalid command pattern"):
        parse_policy("bad", path)
