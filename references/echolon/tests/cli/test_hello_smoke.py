"""End-to-end smoke test for `echolon hello`.

Sets ``ECHOLON_INIT_TEST_STUB=1`` so the underlying ``init`` command writes
a tiny synthetic dataset instead of calling akshare. Confirms the hello flow
produces the PathsConfig-compatible workspace layout that ``_run_backtest``
reads from.
"""
from __future__ import annotations
import os
import subprocess
import sys


def test_hello_creates_demo_and_runs_backtest(tmp_path):
    env = os.environ.copy()
    env["ECHOLON_INIT_TEST_STUB"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main", "hello"],
        cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    )

    demo = tmp_path / "echolon-hello"
    assert demo.is_dir()
    assert (demo / ".echolon-workspace.json").is_file()
    # Consolidated layout: source data (OHLCV + main_contract co-located)
    # under data/{market}/{instrument}/.
    assert (demo / "data" / "SHFE" / "aluminum" / "sort_by_contract").is_dir()
    assert (demo / "data" / "SHFE" / "aluminum" / "main_contract.csv").is_file()
    # Strategy scaffold from template.
    assert (demo / "strategy" / "baseline").is_dir()
    # READMEs for both trees.
    assert (demo / "data" / "README.md").is_file()
    assert (demo / "workspace" / "README.md").is_file()
    # Backtest artifacts land under workspace/backtest/, not output/.
    assert not (demo / "output").exists()
    # Legacy workspace/data/ subtree should not exist — consolidation moved
    # all source data into data/.
    assert not (demo / "workspace" / "data" / "market_data").exists()

    out = result.stdout
    assert "echolon-hello" in out
    # Output may show backtest result or a clean validation gate — both fine.
