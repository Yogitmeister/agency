"""Windows PTY supervisor and target-side Agency policy enforcement."""

from __future__ import annotations

import codecs
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from . import ledger
from .policy import CommandPolicy

POLL_SECONDS = 0.25


class _RawConsoleMode:
    """Put the real console in VT passthrough mode while the child PTY is active."""

    STD_INPUT = -10
    STD_OUTPUT = -11
    PROCESSED_INPUT = 0x0001
    LINE_INPUT = 0x0002
    ECHO_INPUT = 0x0004
    VT_INPUT = 0x0200
    VT_OUTPUT = 0x0004
    NO_AUTO_RETURN = 0x0008

    def __init__(self) -> None:
        self.kernel32 = ctypes.windll.kernel32
        self.stdin = self.kernel32.GetStdHandle(self.STD_INPUT)
        self.stdout = self.kernel32.GetStdHandle(self.STD_OUTPUT)
        self.old_in = wintypes.DWORD()
        self.old_out = wintypes.DWORD()
        self.active = False

    def __enter__(self):
        if not self.kernel32.GetConsoleMode(self.stdin, ctypes.byref(self.old_in)):
            return self
        if not self.kernel32.GetConsoleMode(self.stdout, ctypes.byref(self.old_out)):
            return self
        new_in = (
            self.old_in.value
            & ~self.PROCESSED_INPUT
            & ~self.LINE_INPUT
            & ~self.ECHO_INPUT
        ) | self.VT_INPUT
        new_out = self.old_out.value | self.VT_OUTPUT | self.NO_AUTO_RETURN
        self.active = bool(
            self.kernel32.SetConsoleMode(self.stdin, new_in)
            and self.kernel32.SetConsoleMode(self.stdout, new_out)
        )
        return self

    def __exit__(self, *_):
        if self.active:
            self.kernel32.SetConsoleMode(self.stdin, self.old_in.value)
            self.kernel32.SetConsoleMode(self.stdout, self.old_out.value)
        return False


def _pump_out(proc) -> None:
    while proc.isalive():
        try:
            value = proc.read(4096)
        except Exception:
            return
        if not value:
            time.sleep(0.02)
            continue
        try:
            sys.stdout.write(value)
            sys.stdout.flush()
        except Exception:
            return


def _pump_in(proc) -> None:
    stream = sys.stdin.buffer
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while proc.isalive():
        try:
            value = stream.read(1)
        except Exception:
            return
        if not value:
            return
        for character in decoder.decode(value):
            try:
                if character == "\x03":
                    proc.sendintr()
                else:
                    proc.write(character)
            except Exception:
                return


def _authorize_request(session_id: str, request: dict, policy: CommandPolicy) -> tuple[bool, str]:
    try:
        if str(request.get("targetId")) != session_id:
            return False, "request target does not match this supervisor"
        requester = request.get("requesterId")
        if not request.get("operator"):
            if not requester or not ledger.has_custody(str(requester), session_id):
                return False, "requester has no custody over this session"
        return policy.accepts(str(request.get("command", "")))
    except ledger.LedgerError as exc:
        return False, f"invalid custody record: {exc}"


def _watch_requests(proc, session_id: str, policy: CommandPolicy) -> None:
    while proc.isalive():
        for path, request in ledger.claim_requests(session_id):
            request_id = str(request.get("requestId", ""))
            try:
                ledger.validate_id(request_id)
                accepted, detail = _authorize_request(session_id, request, policy)
                if not accepted:
                    ledger.write_receipt(session_id, request_id, "refused", detail)
                    continue
                command = str(request["command"]).strip()
                proc.write(command + "\r")
                ledger.write_receipt(
                    session_id,
                    request_id,
                    "injected",
                    f"{detail}; written to PTY",
                )
            except Exception as exc:
                try:
                    ledger.write_receipt(session_id, request_id, "failed", str(exc))
                except ledger.LedgerError:
                    pass
            finally:
                path.unlink(missing_ok=True)
        time.sleep(POLL_SECONDS)


def supervise(
    *,
    session_id: str,
    name: str,
    parent_id: str | None,
    policy: CommandPolicy,
    argv: list[str],
) -> int:
    if sys.platform != "win32":
        print("agency: the current supervisor is Windows-first", file=sys.stderr)
        return 2
    try:
        import winpty
    except ImportError:
        print("agency: install pywinpty first", file=sys.stderr)
        return 2
    if not argv:
        print("agency: no child command supplied after --", file=sys.stderr)
        return 2

    os.environ["AGENCY_SESSION_ID"] = session_id
    os.environ["AGENCY_SESSION_NAME"] = name
    os.environ["AGENCY_POLICY"] = policy.name
    if policy.source.startswith("bundled:"):
        os.environ.pop("AGENCY_POLICY_FILE", None)
    else:
        os.environ["AGENCY_POLICY_FILE"] = policy.source
    if parent_id:
        os.environ["AGENCY_PARENT_ID"] = parent_id
    else:
        os.environ.pop("AGENCY_PARENT_ID", None)

    try:
        size = os.get_terminal_size()
        dimensions = (size.lines, size.columns)
    except OSError:
        dimensions = (50, 180)

    ledger.register_session(
        session_id,
        name=name,
        parent_id=parent_id,
        supervisor_pid=os.getpid(),
        child_pid=0,
        policy=policy.name,
        argv=argv,
        state="launching",
    )
    try:
        proc = winpty.PtyProcess.spawn(argv, cwd=os.getcwd(), dimensions=dimensions)
    except Exception as exc:
        ledger.end_session(session_id, 2)
        print(f"agency: failed to spawn {argv!r}: {exc}", file=sys.stderr)
        return 2

    ledger.register_session(
        session_id,
        name=name,
        parent_id=parent_id,
        supervisor_pid=os.getpid(),
        child_pid=proc.pid,
        policy=policy.name,
        argv=argv,
        state="running",
    )
    print(
        f"[agency] {name} {session_id[:8]} supervised with policy={policy.name}\r\n",
        flush=True,
    )
    try:
        with _RawConsoleMode():
            threading.Thread(target=_pump_out, args=(proc,), daemon=True).start()
            threading.Thread(target=_pump_in, args=(proc,), daemon=True).start()
            _watch_requests(proc, session_id, policy)
        return_code = getattr(proc, "exitstatus", None)
    finally:
        return_code = getattr(proc, "exitstatus", None)
        ledger.end_session(session_id, return_code)
        try:
            proc.close()
        except Exception:
            pass
    return int(return_code or 0)
