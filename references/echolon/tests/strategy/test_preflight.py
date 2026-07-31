"""Preflight validation runs all strategy checks up-front and raises the first
catalog error encountered."""
from pathlib import Path
from textwrap import dedent

import pytest


def _make_valid_strategy(root: Path) -> None:
    """Write a minimal valid 6-file strategy tree."""
    (root / "entry.py").write_text(dedent("""
        from echolon.strategy.component import EntryComponent
        class entry_rule(EntryComponent):
            def generate_signal(self, bar):
                return None
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
    (root / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))
    (root / "strategy_indicator_list.json").write_text('{}', encoding="utf-8")


def test_preflight_valid_strategy_passes(tmp_path):
    _make_valid_strategy(tmp_path)
    from echolon.strategy.preflight import preflight
    # Should not raise
    preflight(tmp_path)


def test_preflight_missing_file_raises_str_001(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "sizer.py").unlink()

    from echolon.strategy.preflight import preflight
    from echolon.errors import StrategyStructureError

    with pytest.raises(StrategyStructureError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "STR-001"
    assert "sizer.py" in str(exc.value)


def test_preflight_missing_class_raises_str_002(tmp_path):
    _make_valid_strategy(tmp_path)
    # Rewrite entry.py with a wrong class name
    (tmp_path / "entry.py").write_text(dedent("""
        class NotEntry:
            pass
    """))

    from echolon.strategy.preflight import preflight
    from echolon.errors import StrategyStructureError

    with pytest.raises(StrategyStructureError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "STR-002"


def test_preflight_missing_params_key_raises_prm_002(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            # missing exit_params, risk_params, sizer_params
        }
    """))

    from echolon.strategy.preflight import preflight
    from echolon.errors import EchelonError

    with pytest.raises(EchelonError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "PRM-002"


def test_preflight_missing_printlog_raises_prm_001(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {},  # missing printlog
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))

    from echolon.strategy.preflight import preflight
    from echolon.errors import EchelonError

    with pytest.raises(EchelonError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "PRM-001"


def test_preflight_fails_fast_on_first_check(tmp_path):
    """When multiple things are wrong, preflight raises the FIRST check's error."""
    _make_valid_strategy(tmp_path)
    # Break both STR-001 (missing file) and PRM-002 (missing params key)
    (tmp_path / "sizer.py").unlink()
    (tmp_path / "strategy_params.py").write_text("DEFAULT_PARAMS = {}", encoding="utf-8")

    from echolon.strategy.preflight import preflight
    from echolon.errors import StrategyStructureError

    with pytest.raises(StrategyStructureError) as exc:
        preflight(tmp_path)
    # STR-001 comes first in the check order
    assert exc.value.code == "STR-001"


def test_load_strategy_from_dir_calls_preflight(tmp_path):
    """loader.load_strategy_from_dir must call preflight() so the PRM-*
    checks fire BEFORE any import attempt. Without preflight delegation,
    the loader's inline checks only cover STR-001/002 and PRM-001/002
    would only surface later at backtest-time."""
    _make_valid_strategy(tmp_path)
    # Break PRM-002: remove a required params key. Today the loader's
    # inline checks (STR-001, STR-002) pass — preflight delegation is
    # what catches PRM-002 at load time.
    (tmp_path / "strategy_params.py").write_text(
        "DEFAULT_PARAMS = {'entry_params': {'printlog': False}}"
    )

    from echolon.strategy.loader import load_strategy_from_dir
    from echolon.errors import EchelonError

    with pytest.raises(EchelonError) as exc:
        load_strategy_from_dir(tmp_path)
    assert exc.value.code == "PRM-002"


def test_canary_baseline_passes_preflight():
    """Canary baseline strategy must satisfy preflight without a phantom component.py."""
    from echolon.strategy.preflight import preflight

    baseline = Path(__file__).parents[1] / "fixtures" / "baselines" / "aluminum_baseline"
    assert baseline.exists(), f"canary baseline missing at {baseline}"
    assert not (baseline / "component.py").exists(), (
        "baseline must NOT contain a strategy-local component.py — that file "
        "is a phantom requirement removed from REQUIRED_FILES."
    )
    preflight(baseline)
