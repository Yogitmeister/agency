import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="the extracted supervisor is Windows-first")
def test_real_pty_claims_and_injects_an_authorized_request(tmp_path):
    env = os.environ.copy()
    env["AGENCY_HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    env.pop("AGENCY_SESSION_ID", None)

    target = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agency_pty",
            "start",
            "--session-id",
            "e2e-target",
            "--name",
            "e2e-target",
            "--policy",
            "context",
            "--",
            sys.executable,
            "-u",
            "-c",
            "line=input(); print('received:' + line, flush=True)",
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    meta_path = tmp_path / "sessions" / "e2e-target" / "meta.json"
    deadline = time.time() + 10
    while time.time() < deadline:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("state") == "running":
                break
        time.sleep(0.05)
    else:
        target.kill()
        raise AssertionError("supervisor did not reach running state")

    request = subprocess.run(
        [
            sys.executable,
            "-m",
            "agency_pty",
            "request",
            "--to",
            "e2e-target",
            "--command",
            "/compact keep state",
            "--operator",
            "--wait",
            "5",
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output, _ = target.communicate(timeout=10)

    assert request.returncode == 0, request.stdout + request.stderr
    assert "injected:" in request.stdout
    assert "received:/compact keep state" in output
    ended = json.loads(meta_path.read_text(encoding="utf-8"))
    assert ended["state"] == "ended"
    assert ended["returnCode"] == 0
