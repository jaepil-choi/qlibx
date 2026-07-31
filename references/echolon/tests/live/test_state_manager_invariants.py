"""Invariant tests for StateManager + PendingExitIntent — state-shape guards."""
import json
from pathlib import Path

from echolon.strategy.state_manager import StateManager, PendingExitIntent


def _make_pending(intent: str = "EXIT_LONG", original_size: int = 3,
                  remaining_size: int = 3) -> PendingExitIntent:
    return PendingExitIntent(
        intent=intent,
        original_size=original_size,
        remaining_size=remaining_size,
        attempts_so_far=0,
        original_decision_time="2026-05-08T21:00:00",
        last_attempt_time="2026-05-08T21:00:00",
        cycles_pending=1,
    )


def test_pending_exit_remaining_size_never_exceeds_original(tmp_path):
    """remaining_size <= original_size is an invariant callers should respect.
    Verify a roundtrip does not corrupt it."""
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(_make_pending(original_size=3, remaining_size=3))
    sm.save_state()
    # Reload + verify
    sm2 = StateManager(state_path=str(state_path))
    sm2.load_state()
    pending = sm2.get_pending_exit_intent()
    assert pending is not None
    assert pending.remaining_size <= pending.original_size


def test_pending_exit_attempts_so_far_increases_via_update(tmp_path):
    """After update, attempts_so_far must be > previous value."""
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(_make_pending())
    sm.save_state()

    sm2 = StateManager(state_path=str(state_path))
    sm2.load_state()
    p = sm2.get_pending_exit_intent()
    p.attempts_so_far += 1
    sm2.set_pending_exit_intent(p)
    sm2.save_state()

    sm3 = StateManager(state_path=str(state_path))
    sm3.load_state()
    final = sm3.get_pending_exit_intent()
    assert final is not None
    assert final.attempts_so_far == 1


def test_state_save_load_roundtrip_preserves_position(tmp_path):
    """Position fields survive save -> load."""
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    state = sm.load_state()
    state.position_symbol = "al2606.SF"
    state.position_size = 2.0
    state.position_side = "LONG"
    state.position_entry_price = 24600.0
    sm.save_state()

    sm2 = StateManager(state_path=str(state_path))
    state2 = sm2.load_state()
    assert state2.position_symbol == "al2606.SF"
    assert state2.position_size == 2.0
    assert state2.position_side == "LONG"
    assert state2.position_entry_price == 24600.0


def test_state_save_is_atomic(tmp_path):
    """No .tmp file should be left behind after a successful save."""
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.save_state()
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_clear_pending_exit_intent_removes_from_state(tmp_path):
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.set_pending_exit_intent(_make_pending())
    sm.save_state()
    sm.clear_pending_exit_intent()
    sm.save_state()

    sm2 = StateManager(state_path=str(state_path))
    sm2.load_state()
    assert sm2.get_pending_exit_intent() is None


def test_state_version_field_present_on_save(tmp_path):
    """version-tagged state for future migration safety."""
    state_path = tmp_path / "strategy_state.json"
    state_path.write_text("{}", encoding="utf-8")
    sm = StateManager(state_path=str(state_path))
    sm.load_state()
    sm.save_state()
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert "version" in raw
    assert raw["version"] in ("1.0", "1.1")
