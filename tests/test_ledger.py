import json
import os

import pytest

from agency_pty import ledger


@pytest.fixture
def agency_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_HOME", str(tmp_path))
    return tmp_path


def register(session_id, name, parent_id=None):
    return ledger.register_session(
        session_id,
        name=name,
        parent_id=parent_id,
        supervisor_pid=os.getpid(),
        child_pid=os.getpid(),
        policy="context",
        argv=["claude"],
    )


def test_custody_flows_downward_only(agency_home):
    register("root", "root")
    register("child", "child", "root")
    register("grandchild", "grandchild", "child")
    register("peer", "peer")

    assert ledger.has_custody("root", "root")
    assert ledger.has_custody("root", "grandchild")
    assert ledger.has_custody("child", "grandchild")
    assert not ledger.has_custody("child", "root")
    assert not ledger.has_custody("peer", "child")


def test_unrelated_peer_cannot_queue(agency_home):
    register("root", "root")
    register("peer", "peer")
    with pytest.raises(ledger.LedgerError, match="neither self nor"):
        ledger.queue_request(requester_id="peer", target_id="root", command="/compact")


def test_request_queue_rejects_prompt_text_before_writing_files(agency_home):
    register("root", "root")
    with pytest.raises(ledger.LedgerError, match="only slash commands"):
        ledger.queue_request(
            requester_id="root",
            target_id="root",
            command="please compact",
        )
    assert not (agency_home / "sessions" / "root" / "requests").exists()


def test_descendant_request_has_durable_queue_and_receipt(agency_home):
    register("root", "root")
    register("child", "child", "root")
    request = ledger.queue_request(
        requester_id="root", target_id="child", command="/effort high"
    )
    request_id = request["requestId"]
    queued = ledger.get_receipt("child", request_id)
    assert queued["state"] == "queued"

    claimed = list(ledger.claim_requests("child"))
    assert len(claimed) == 1
    assert claimed[0][1]["command"] == "/effort high"


def test_operator_override_is_explicit(agency_home):
    register("target", "target")
    request = ledger.queue_request(
        requester_id=None,
        target_id="target",
        command="/compact",
        operator=True,
    )
    assert request["operator"] is True


def test_session_identity_cannot_use_operator_override(agency_home):
    register("peer", "peer")
    register("target", "target")
    with pytest.raises(ledger.LedgerError, match="unavailable inside"):
        ledger.queue_request(
            requester_id="peer",
            target_id="target",
            command="/compact",
            operator=True,
        )


def test_active_names_are_unique_and_ended_names_can_be_reused(agency_home):
    register("first", "reviewer")
    with pytest.raises(ledger.LedgerError, match="name already exists"):
        register("second", "reviewer")
    ledger.end_session("first", 0)
    register("second", "reviewer")
    assert ledger.resolve_session("reviewer") == "second"


def test_dead_supervisor_does_not_block_name_reuse_or_resolution(agency_home):
    ledger.register_session(
        "stale",
        name="reviewer",
        parent_id=None,
        supervisor_pid=999_999_999,
        child_pid=999_999_999,
        policy="context",
        argv=["claude"],
    )
    register("replacement", "reviewer")
    assert ledger.resolve_session("reviewer") == "replacement"


def test_malformed_liveness_fields_are_treated_as_inactive(agency_home):
    path = agency_home / "sessions" / "broken" / "meta.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "sessionId": "broken",
                "name": "broken",
                "state": "running",
                "supervisorPid": "not-a-pid",
                "startedAtMs": "not-a-time",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ledger.LedgerError, match="unknown supervised session"):
        ledger.resolve_session("broken")


def test_dead_requester_cannot_queue_to_live_descendant(agency_home):
    ledger.register_session(
        "stale-parent",
        name="stale-parent",
        parent_id=None,
        supervisor_pid=999_999_999,
        child_pid=999_999_999,
        policy="context",
        argv=["claude"],
    )
    register("child", "child", "stale-parent")
    with pytest.raises(ledger.LedgerError, match="requester supervisor is not active"):
        ledger.queue_request(
            requester_id="stale-parent",
            target_id="child",
            command="/compact",
        )


def test_active_session_id_cannot_be_redefined(agency_home):
    register("root", "root")
    with pytest.raises(ledger.LedgerError, match="session id already exists"):
        ledger.register_session(
            "root",
            name="hijack",
            parent_id=None,
            supervisor_pid=99,
            child_pid=100,
            policy="all-slash",
            argv=["other"],
        )


def test_spawn_reservation_can_be_claimed_once(agency_home):
    ledger.register_session(
        "child",
        name="child",
        parent_id="root",
        supervisor_pid=0,
        child_pid=0,
        policy="context",
        argv=["claude"],
        state="launching",
    )
    claimed = ledger.register_session(
        "child",
        name="child",
        parent_id="root",
        supervisor_pid=42,
        child_pid=43,
        policy="context",
        argv=["claude"],
        state="running",
    )
    assert claimed["state"] == "running"
    assert claimed["supervisorPid"] == 42


def test_meta_contains_no_command_secret(agency_home):
    register("root", "root")
    meta = json.loads((agency_home / "sessions" / "root" / "meta.json").read_text())
    assert set(meta) >= {"sessionId", "parentId", "policy", "state"}
