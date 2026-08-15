"""Command-line interface for Agency."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid

from . import ledger
from .policy import PolicyError, parse_policy
from .supervisor import supervise


def _split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def _requester() -> str | None:
    value = os.environ.get("AGENCY_SESSION_ID")
    return ledger.validate_id(value) if value else None


def _cmd_start(argv: list[str]) -> int:
    own, command = _split_command(argv)
    parser = argparse.ArgumentParser(prog="agency start")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--parent-id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--policy", default="context")
    parser.add_argument(
        "--policy-file",
        default=os.environ.get("AGENCY_POLICY_FILE", ""),
        help="JSON policy file; defaults to Agency's bundled command-policy.json",
    )
    args = parser.parse_args(own)
    session_id = args.session_id or str(uuid.uuid4())
    name = args.name or f"agency-{session_id[:8]}"
    parent_id = ledger.validate_id(args.parent_id) if args.parent_id else None
    if parent_id and _requester() != parent_id:
        raise ledger.LedgerError(
            "a supervised parent may only launch a child under its own session id"
        )
    policy = parse_policy(args.policy, args.policy_file or None)
    return supervise(
        session_id=ledger.validate_id(session_id),
        name=ledger.validate_name(name),
        parent_id=parent_id,
        policy=policy,
        argv=command,
    )


def _cmd_request(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agency request")
    parser.add_argument("--to", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--wait", type=float, default=0)
    parser.add_argument(
        "--operator",
        action="store_true",
        help="explicit human override; autonomous sessions must not use this flag",
    )
    args = parser.parse_args(argv)
    requester = _requester()
    if args.operator and requester:
        raise ledger.LedgerError(
            "operator override is unavailable inside a supervised session"
        )
    target = ledger.resolve_session(args.to, requester)
    request = ledger.queue_request(
        requester_id=requester,
        target_id=target,
        command=args.command,
        operator=args.operator,
    )
    request_id = str(request["requestId"])
    print(f"queued {request_id} -> {target}")
    if args.wait <= 0:
        return 0
    deadline = time.time() + args.wait
    while time.time() < deadline:
        receipt = ledger.get_receipt(target, request_id)
        if receipt.get("state") != "queued":
            print(f"{receipt['state']}: {receipt.get('detail', '')}")
            return 0 if receipt["state"] == "injected" else 3
        time.sleep(0.1)
    print("still queued: target supervisor did not claim the request before timeout")
    return 4


def _cmd_spawn(argv: list[str]) -> int:
    own, command = _split_command(argv)
    parser = argparse.ArgumentParser(prog="agency spawn")
    parser.add_argument("--name", required=True)
    parser.add_argument("--policy", default="context")
    parser.add_argument(
        "--policy-file",
        default=os.environ.get("AGENCY_POLICY_FILE", ""),
        help="JSON policy file; inherits the parent's custom file when present",
    )
    args = parser.parse_args(own)
    parent = _requester()
    if not parent:
        raise ledger.LedgerError("spawn must run inside a supervised session")
    if not command:
        raise ledger.LedgerError("spawn requires a command after --")
    policy = parse_policy(args.policy, args.policy_file or None)
    child_id = str(uuid.uuid4())
    child_name = ledger.validate_name(args.name)
    launch = [
        sys.executable,
        "-m",
        "agency_pty",
        "start",
        "--session-id",
        child_id,
        "--parent-id",
        parent,
        "--name",
        child_name,
        "--policy",
        policy.name,
    ]
    if not policy.source.startswith("bundled:"):
        launch.extend(["--policy-file", policy.source])
    launch.extend(["--", *command])
    ledger.register_session(
        child_id,
        name=child_name,
        parent_id=parent,
        supervisor_pid=0,
        child_pid=0,
        policy=policy.name,
        argv=command,
        state="launching",
    )
    creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    try:
        subprocess.Popen(launch, cwd=os.getcwd(), creationflags=creation_flags, close_fds=True)
    except OSError:
        ledger.end_session(child_id, 2)
        raise
    print(f"spawned {child_name} id={child_id} parent={parent}")
    return 0


def _cmd_tree(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agency tree")
    parser.parse_args(argv)
    records = list(ledger.iter_sessions())
    children: dict[str | None, list[dict]] = {}
    ids = {str(record.get("sessionId")) for record in records}
    for record in records:
        parent = record.get("parentId")
        if parent not in ids:
            parent = None
        children.setdefault(parent, []).append(record)

    def emit(parent: str | None, depth: int) -> None:
        for record in sorted(children.get(parent, []), key=lambda item: str(item.get("name"))):
            print(
                f"{'  ' * depth}{record.get('name')} {str(record.get('sessionId'))[:8]} "
                f"[{record.get('state')}] policy={record.get('policy')}"
            )
            emit(str(record.get("sessionId")), depth + 1)

    emit(None, 0)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: agency {start|request|spawn|tree} ...")
        return 0
    command, rest = argv[0], argv[1:]
    try:
        if command == "start":
            return _cmd_start(rest)
        if command == "request":
            return _cmd_request(rest)
        if command == "spawn":
            return _cmd_spawn(rest)
        if command == "tree":
            return _cmd_tree(rest)
        print(f"agency: unknown command {command!r}", file=sys.stderr)
        return 2
    except (ledger.LedgerError, PolicyError) as exc:
        print(f"agency: {exc}", file=sys.stderr)
        return 2
