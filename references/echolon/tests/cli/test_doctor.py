"""Smoke test for `echolon doctor`."""
from __future__ import annotations
import json
import os
import subprocess
import sys


def test_doctor_runs_and_emits_json():
    result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main", "doctor", "--json"],
        env=os.environ.copy(),
        capture_output=True, text=True, timeout=30,
    )
    payload = json.loads(result.stdout)
    assert "checks" in payload
    names = [c["name"] for c in payload["checks"]]
    assert "ta-lib" in names
    assert "akshare" in names
