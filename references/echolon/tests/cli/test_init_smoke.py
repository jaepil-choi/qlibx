"""Smoke tests for `echolon init`. Network calls stubbed via env var."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path


def test_template_only_init_preserves_legacy_behavior(tmp_path):
    """`echolon init <dir> --template minimal` (no instrument flags) just scaffolds."""
    target = tmp_path / "scaffold-only"
    result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main",
         "init", str(target), "--template", "minimal"],
        cwd=str(tmp_path), env=os.environ.copy(),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert target.is_dir()
    assert (target / "entry.py").is_file() or (target / "strategy.py").is_file()
    # No workspace marker — this wasn't a full init.
    assert not (target / ".echolon-workspace.json").exists()


def test_full_init_creates_workspace_with_data_and_strategy(tmp_path):
    workspace = tmp_path / "ws"
    env = os.environ.copy()
    env["ECHOLON_INIT_TEST_STUB"] = "1"  # bypass akshare network call

    result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main",
         "init", str(workspace),
         "--market", "SHFE", "--instrument", "aluminum",
         "--start", "2024-01-01", "--end", "2024-01-15",
         "--template", "minimal"],
        cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Workspace marker + recoverable context.
    marker = workspace / ".echolon-workspace.json"
    assert marker.is_file()
    m = json.loads(marker.read_text(encoding="utf-8"))
    assert m["instrument"] == "aluminum"
    assert m["instrument_code"] == "al"
    assert m["market"] == "SHFE"

    # Consolidated single-tree layout: data/{market}/{instrument}/ holds
    # main_contract.csv co-located with the OHLCV. workspace/ holds only
    # regenerable working artifacts.
    assert (workspace / "data" / "SHFE" / "aluminum" / "sort_by_contract").is_dir()
    assert (workspace / "data" / "SHFE" / "aluminum" / "main_contract.csv").is_file()
    assert (workspace / "data" / "SHFE" / "aluminum" / "sort_by_date.csv").is_file()
    assert (workspace / "data" / "SHFE" / "aluminum" / "trading_calendar.csv").is_file()

    # Legacy workspace/data/market_data/ subtree should NOT be created —
    # the consolidation moved everything into data/.
    assert not (workspace / "workspace" / "data" / "market_data").exists()
    # Legacy split data/{market}/{code}/main_contract.csv should NOT exist —
    # it now lives alongside OHLCV under data/{market}/{instrument}/.
    assert not (workspace / "data" / "SHFE" / "al").exists()

    # READMEs explain the data/ source-tree and workspace/ regenerable-tree.
    assert (workspace / "data" / "README.md").is_file()
    assert (workspace / "workspace" / "README.md").is_file()

    # Scaffolded strategy.
    strategy_dir = workspace / "strategy" / "baseline"
    assert strategy_dir.is_dir()
    assert (strategy_dir / "entry.py").is_file() or (strategy_dir / "strategy.py").is_file()

    # Backtest artifacts land under workspace/backtest/ when the user runs
    # `echolon backtest single`. No output/ dir is created.
    assert not (workspace / "output").exists()

    # Marker carries `paths` overrides so the chosen layout is workspace-local.
    assert "paths" in m
    assert m["paths"]["market_data_dir"] == "data"
    assert m["paths"]["raw_data_dir"] == "data"
    assert m["paths"]["indicators_backtest_dir"] == "workspace/indicators"
