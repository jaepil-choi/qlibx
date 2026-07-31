"""`echolon backtest single --paths-config foo.json` overrides workspace marker.

Cheap smoke test that the CLI flag is wired through to PathsConfig — full
backtest semantics are exercised by ``test_hello_smoke.py``.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys


def test_paths_config_flag_loads_json(tmp_path):
    """When --paths-config <file.json> is supplied, the CLI prints a marker
    line confirming the file was loaded, and the resolved paths win over any
    workspace marker. We only assert the flag is recognised and the message
    is emitted — the run itself fails FileNotFound (no data), which is fine."""
    env = os.environ.copy()
    env["ECHOLON_INIT_TEST_STUB"] = "1"

    # Build a minimal workspace via init (gives us a strategy/baseline/ to run).
    workspace = tmp_path / "ws"
    init_result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main",
         "init", str(workspace),
         "--market", "SHFE", "--instrument", "aluminum",
         "--start", "2024-01-01", "--end", "2024-01-15",
         "--template", "minimal"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )
    assert init_result.returncode == 0, init_result.stderr

    # Hand-edited paths_config.json overriding marker.
    cfg = tmp_path / "my_paths.json"
    cfg.write_text(json.dumps({
        "project_root": str(workspace),
        "market_data_dir": str(workspace / "data"),
        "raw_data_dir": str(workspace / "data"),
        "indicators_backtest_dir": str(workspace / "workspace" / "indicators"),
    }))

    bt_result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main",
         "backtest", "single",
         str(workspace / "strategy" / "baseline"),
         "--paths-config", str(cfg)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=180,
    )
    # Flag-acknowledged line MUST appear in stdout regardless of downstream
    # success; it's the contract we're testing.
    assert "Paths from --paths-config" in bt_result.stdout, (
        f"missing --paths-config ack line\nstdout:\n{bt_result.stdout}\n"
        f"stderr:\n{bt_result.stderr}"
    )
