"""Workspace marker file (.echolon-workspace.json) read/write/walk-up."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest

from echolon.native.workspace import (
    WORKSPACE_MARKER,
    write_marker,
    read_marker,
    find_workspace_root,
    WorkspaceNotFoundError,
)


def test_write_then_read_roundtrip(tmp_path):
    write_marker(tmp_path, market="SHFE", instrument="zinc",
                 instrument_code="zn", frequency="interday",
                 bar_size="1d", date_range=("2022-01-01", "2024-12-31"),
                 data_source="akshare", initial_capital=200000.0)
    m = read_marker(tmp_path)
    assert m["market"] == "SHFE"
    assert m["instrument"] == "zinc"
    assert m["instrument_code"] == "zn"
    assert m["date_range"] == ["2022-01-01", "2024-12-31"]
    assert m["initial_capital"] == 200000.0


def test_find_workspace_root_walks_up(tmp_path):
    write_marker(tmp_path, market="SHFE", instrument="aluminum",
                 instrument_code="al", frequency="interday",
                 bar_size="1d", date_range=("2023-01-01", "2024-12-31"),
                 data_source="bundled", initial_capital=200000.0)
    nested = tmp_path / "strategy" / "baseline" / "subdir"
    nested.mkdir(parents=True)
    found = find_workspace_root(nested)
    assert found == tmp_path


def test_find_workspace_root_raises_when_absent(tmp_path):
    with pytest.raises(WorkspaceNotFoundError):
        find_workspace_root(tmp_path)
