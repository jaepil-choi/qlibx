"""Tests for atomic state writes + heartbeat emission."""
import json
from pathlib import Path

from echolon._internal.atomic_state import (
    STATE_SCHEMA_VERSION,
    HEARTBEAT_SCHEMA_VERSION,
    write_state_atomically,
    update_heartbeat,
)


def test_write_state_atomically_includes_schema_version(tmp_path):
    target = tmp_path / "strategy_state.json"
    payload = {"slot_id": "al_s1", "current_equity": 100000.0}

    write_state_atomically(str(target), payload)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == STATE_SCHEMA_VERSION
    assert loaded["slot_id"] == "al_s1"
    assert loaded["current_equity"] == 100000.0


def test_write_state_atomically_leaves_no_tmp_file(tmp_path):
    """Writer must create .tmp then rename. .tmp must not linger."""
    target = tmp_path / "strategy_state.json"
    target.write_text(json.dumps({"schema_version": "1.0", "slot_id": "old"}))

    write_state_atomically(str(target), {"slot_id": "new"})

    assert not (tmp_path / "strategy_state.json.tmp").exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["slot_id"] == "new"


def test_write_state_atomically_preserves_existing_schema_version(tmp_path):
    """If caller supplies schema_version, don't double-inject."""
    target = tmp_path / "strategy_state.json"
    payload = {"schema_version": "1.0", "slot_id": "al_s1"}

    write_state_atomically(str(target), payload)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0"
    assert list(loaded.keys()).count("schema_version") == 1


def test_update_heartbeat_creates_file_with_schema(tmp_path):
    workspace = tmp_path / "workspace" / "deploy"
    update_heartbeat(str(workspace), slots_alive=["al_s1", "cu_s1"])

    heartbeat_path = workspace / "heartbeat.json"
    assert heartbeat_path.exists()
    loaded = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == HEARTBEAT_SCHEMA_VERSION
    assert loaded["slots_alive"] == ["al_s1", "cu_s1"]
    assert "last_cycle_ts" in loaded


def test_update_heartbeat_sorts_slots(tmp_path):
    """Slot list should be sorted for deterministic output."""
    workspace = tmp_path / "workspace" / "deploy"
    update_heartbeat(str(workspace), slots_alive=["zn_s1", "al_s1", "cu_s1"])
    loaded = json.loads((workspace / "heartbeat.json").read_text(encoding="utf-8"))
    assert loaded["slots_alive"] == ["al_s1", "cu_s1", "zn_s1"]
