from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]


def test_module_cli_exposes_run_report_and_ensemble_use_cases() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(INTEGRATION_ROOT)

    completed = subprocess.run(
        [sys.executable, "-m", "qlib_extended", "--help"],
        cwd=INTEGRATION_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "run" in completed.stdout
    assert "report" in completed.stdout
    assert "ensemble" in completed.stdout
