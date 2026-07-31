"""Preflight compares indicator names in code vs JSON; casing mismatch raises IND-001."""
import json
from pathlib import Path
from textwrap import dedent

import pytest

from echolon.errors import IndicatorError


def _make_strategy_with_indicator_use(root: Path, code_name: str, json_name: str):
    """Create a minimal strategy where entry.py references `code_name` as a
    string literal, but strategy_indicator_list.json declares `json_name`."""
    (root / "entry.py").write_text(dedent(f"""
        from echolon.strategy.component import EntryComponent
        class entry_rule(EntryComponent):
            def generate_signal(self, bar):
                return bar.get({code_name!r})
    """))
    (root / "exit.py").write_text(dedent("""
        from echolon.strategy.component import ExitComponent
        class exit_rule(ExitComponent):
            def should_exit(self, bar, position):
                return None
    """))
    (root / "risk.py").write_text(dedent("""
        from echolon.strategy.component import RiskComponent
        class risk_manager(RiskComponent):
            def can_trade(self, signal, portfolio):
                return signal
    """))
    (root / "sizer.py").write_text(dedent("""
        from echolon.strategy.component import SizerComponent
        class position_sizer(SizerComponent):
            def calculate_size(self, signal, portfolio):
                return 0
    """))
    (root / "component.py").write_text("# marker file", encoding="utf-8")
    (root / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))
    (root / "strategy_indicator_list.json").write_text(json.dumps({
        "indicators": [{"name": json_name, "params": {}}]
    }))


def test_casing_mismatch_raises_ind_001(tmp_path):
    _make_strategy_with_indicator_use(tmp_path, code_name="RSI_14", json_name="rsi_14")

    from echolon.strategy.preflight import preflight

    with pytest.raises(IndicatorError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "IND-001"
    assert "RSI_14" in str(exc.value)
    assert "rsi_14" in str(exc.value)


def test_matching_casing_passes(tmp_path):
    _make_strategy_with_indicator_use(tmp_path, code_name="rsi_14", json_name="rsi_14")

    from echolon.strategy.preflight import preflight

    # No raise — matching casing is fine
    preflight(tmp_path)


def test_code_reference_with_no_json_match_passes(tmp_path):
    """If code uses a string that doesn't correspond to any JSON-declared
    indicator (e.g., 'datetime', 'close'), preflight does not raise IND-001."""
    _make_strategy_with_indicator_use(tmp_path, code_name="datetime", json_name="rsi_14")

    from echolon.strategy.preflight import preflight

    # 'datetime' is unrelated to 'rsi_14' — no raise
    preflight(tmp_path)
