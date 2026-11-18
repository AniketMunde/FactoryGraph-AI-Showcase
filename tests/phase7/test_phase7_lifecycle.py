"""Exercise shutdown of a genuine owned Python process tree, including launchers."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_native_stop_closes_owned_descendants(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import psutil

    from factorygraph.phase7 import cli

    child_code = "import time; time.sleep(90)"
    parent_code = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "print(p.pid,flush=True); time.sleep(90)"
    )
    command = [sys.executable, "-c", parent_code, "factorygraph.phase7.server"]
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    parent = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, **kwargs)
    owned = []
    try:
        child_pid = int(parent.stdout.readline())
        process = psutil.Process(parent.pid)
        owned = [process, *process.children(recursive=True)]
        assert child_pid in {p.pid for p in owned}
        record = {"api": {"pid": parent.pid, "created": process.create_time(), "command": command}}
        (tmp_path / "processes.json").write_text(json.dumps(record))
        monkeypatch.setattr(cli, "ROOT", Path(tmp_path))
        assert cli.stop()["status"] == "stopped_owned_api_and_dashboard_only"
        assert not (tmp_path / "processes.json").exists()
        assert list(tmp_path.glob("processes-stopped-*.json"))
        assert not [p for p in owned if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    finally:
        for process in reversed(owned):
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.wait(timeout=15)
        if parent.stdout:
            parent.stdout.close()
