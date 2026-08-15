"""Durable custody ledger, request queues, and injection receipts."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .policy import PolicyError, normalize_command

_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class LedgerError(ValueError):
    pass


def now_ms() -> int:
    return int(time.time() * 1_000)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        handle = open_process(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            close_handle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def record_is_active(record: dict[str, Any], *, at_ms: int | None = None) -> bool:
    state = record.get("state")
    if state not in {"launching", "running"}:
        return False
    try:
        supervisor_pid = int(record.get("supervisorPid") or 0)
        started_at_ms = int(record.get("startedAtMs") or 0)
    except (TypeError, ValueError):
        return False
    if supervisor_pid > 0:
        return _pid_is_alive(supervisor_pid)
    if state != "launching":
        return False
    age_ms = (now_ms() if at_ms is None else at_ms) - started_at_ms
    return 0 <= age_ms <= 30_000


def agency_home() -> Path:
    configured = os.environ.get("AGENCY_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".agency"


def validate_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise LedgerError("session id must contain only letters, digits, hyphens, or underscores")
    return value


def validate_name(value: str) -> str:
    if not _NAME.fullmatch(value):
        raise LedgerError("name must start with a letter or digit and contain only . _ or -")
    return value


def session_dir(session_id: str) -> Path:
    session_id = validate_id(session_id)
    root = agency_home().resolve()
    path = (root / "sessions" / session_id).resolve()
    if root not in path.parents:
        raise LedgerError("resolved session path escaped the Agency home")
    return path


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"expected an object in {path}")
    return value


def register_session(
    session_id: str,
    *,
    name: str,
    parent_id: str | None,
    supervisor_pid: int,
    child_pid: int,
    policy: str,
    argv: list[str],
    state: str = "running",
) -> dict[str, Any]:
    validate_id(session_id)
    validate_name(name)
    if parent_id:
        validate_id(parent_id)
    meta_path = session_dir(session_id) / "meta.json"
    existing_same_id: dict[str, Any] | None = None
    if meta_path.exists():
        existing_same_id = _read_json(meta_path)
        immutable = {
            "name": name,
            "parentId": parent_id,
            "policy": policy,
            "argv": argv,
        }
        same_identity = all(existing_same_id.get(key) == value for key, value in immutable.items())
        claimable_reservation = (
            existing_same_id.get("state") == "launching"
            and existing_same_id.get("supervisorPid") in {0, supervisor_pid}
            and same_identity
        )
        same_supervisor = (
            existing_same_id.get("state") in {"launching", "running"}
            and existing_same_id.get("supervisorPid") == supervisor_pid
            and same_identity
        )
        if not (claimable_reservation or same_supervisor):
            raise LedgerError(f"supervised session id already exists: {session_id}")
    for existing in iter_sessions():
        if (
            existing.get("sessionId") != session_id
            and existing.get("name") == name
            and record_is_active(existing)
        ):
            raise LedgerError(f"active supervised session name already exists: {name}")
    record = {
        "schema": 1,
        "sessionId": session_id,
        "name": name,
        "parentId": parent_id,
        "supervisorPid": supervisor_pid,
        "childPid": child_pid,
        "policy": policy,
        "argv": argv,
        "state": state,
        "startedAtMs": (
            existing_same_id.get("startedAtMs", now_ms())
            if existing_same_id
            else now_ms()
        ),
    }
    _atomic_json(meta_path, record)
    return record


def end_session(session_id: str, return_code: int | None) -> None:
    path = session_dir(session_id) / "meta.json"
    try:
        record = _read_json(path)
    except LedgerError:
        return
    record.update({"state": "ended", "endedAtMs": now_ms(), "returnCode": return_code})
    _atomic_json(path, record)


def get_session(session_id: str) -> dict[str, Any]:
    return _read_json(session_dir(session_id) / "meta.json")


def iter_sessions() -> Iterable[dict[str, Any]]:
    root = agency_home() / "sessions"
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for meta in sorted(root.glob("*/meta.json")):
        try:
            records.append(_read_json(meta))
        except LedgerError:
            continue
    return records


def resolve_session(reference: str, requester_id: str | None = None) -> str:
    if reference == "self":
        if not requester_id:
            raise LedgerError("'self' requires AGENCY_SESSION_ID")
        return validate_id(requester_id)
    records = list(iter_sessions())
    active = [r for r in records if record_is_active(r)]
    exact = [r for r in active if r.get("sessionId") == reference or r.get("name") == reference]
    if len(exact) == 1:
        return str(exact[0]["sessionId"])
    prefix = [r for r in active if str(r.get("sessionId", "")).startswith(reference)]
    if len(prefix) == 1:
        return str(prefix[0]["sessionId"])
    if len(exact) > 1 or len(prefix) > 1:
        raise LedgerError(f"ambiguous session reference: {reference}")
    raise LedgerError(f"unknown supervised session: {reference}")


def has_custody(requester_id: str, target_id: str) -> bool:
    requester_id = validate_id(requester_id)
    current = validate_id(target_id)
    visited: set[str] = set()
    while current not in visited:
        if current == requester_id:
            return True
        visited.add(current)
        try:
            parent = get_session(current).get("parentId")
        except LedgerError:
            return False
        if not parent:
            return False
        current = str(parent)
    return False


def queue_request(
    *,
    requester_id: str | None,
    target_id: str,
    command: str,
    operator: bool = False,
) -> dict[str, Any]:
    target_id = validate_id(target_id)
    try:
        command = normalize_command(command)
    except PolicyError as exc:
        raise LedgerError(str(exc)) from exc
    target = get_session(target_id)
    if not record_is_active(target):
        raise LedgerError("target supervisor is not active")
    if operator and requester_id:
        raise LedgerError("operator override is unavailable inside a supervised session")
    if not operator:
        if not requester_id:
            raise LedgerError("an autonomous request requires AGENCY_SESSION_ID")
        requester = get_session(requester_id)
        if not record_is_active(requester):
            raise LedgerError("requester supervisor is not active")
        if not has_custody(requester_id, target_id):
            raise LedgerError("refused: target is neither self nor a recorded descendant")
    request_id = str(uuid.uuid4())
    request = {
        "schema": 1,
        "requestId": request_id,
        "requesterId": requester_id,
        "targetId": target_id,
        "operator": bool(operator),
        "command": command,
        "createdAtMs": now_ms(),
    }
    receipt = {
        "schema": 1,
        "requestId": request_id,
        "targetId": target_id,
        "state": "queued",
        "atMs": now_ms(),
    }
    base = session_dir(target_id)
    _atomic_json(base / "receipts" / f"{request_id}.json", receipt)
    _atomic_json(base / "requests" / f"{request_id}.json", request)
    return request


def claim_requests(session_id: str) -> Iterable[tuple[Path, dict[str, Any]]]:
    base = session_dir(session_id)
    request_dir = base / "requests"
    processing = base / "processing"
    processing.mkdir(parents=True, exist_ok=True)
    if not request_dir.is_dir():
        return []
    claimed: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(request_dir.glob("*.json")):
        destination = processing / path.name
        try:
            os.replace(path, destination)
            claimed.append((destination, _read_json(destination)))
        except (OSError, LedgerError):
            continue
    return claimed


def write_receipt(target_id: str, request_id: str, state: str, detail: str) -> dict[str, Any]:
    validate_id(target_id)
    validate_id(request_id)
    receipt = {
        "schema": 1,
        "requestId": request_id,
        "targetId": target_id,
        "state": state,
        "detail": detail,
        "atMs": now_ms(),
    }
    _atomic_json(session_dir(target_id) / "receipts" / f"{request_id}.json", receipt)
    return receipt


def get_receipt(target_id: str, request_id: str) -> dict[str, Any]:
    return _read_json(session_dir(target_id) / "receipts" / f"{request_id}.json")
