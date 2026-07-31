"""Tests for BaseStrategy._log_effective_params — the effective-params audit hook.

Motivation: the trial->deployed parameter mapping silently delivered DEFAULT
values onto the canonical keys components read while orphaning the optimized
values (strip-once prefix mapping vs. single-prefixed optuna names). The audit
hook writes the params the component instances ACTUALLY hold into the per-bar
strategy log row as ``param_{component}_{key}`` columns, so any future mapping
defect is visible directly in qmt_{instrument}.csv (live) and backtest logs.
"""
from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd
import pytest

from echolon.strategy.base import BaseStrategy
from echolon.strategy.logging import CSVStrategyLogger, NullStrategyLogger


def _make_strategy_stub(slogger, **components):
    """A minimal object carrying exactly the attrs _log_effective_params reads.

    The method is exercised UNBOUND on this stub so the test covers the real
    shipped code path without constructing a full engine-backed strategy.
    """
    stub = SimpleNamespace(
        strategy_logger=slogger,
        entry_rule=components.get("entry_rule"),
        exit_rule=components.get("exit_rule"),
        risk_manager=components.get("risk_manager"),
        position_sizer=components.get("position_sizer"),
    )
    return stub


def _open_bar_logger(tmp_path, **kwargs) -> CSVStrategyLogger:
    slogger = CSVStrategyLogger(
        output_dir=str(tmp_path), strategy_name="qmt_test", enabled=True, **kwargs
    )
    slogger.start_new_bar()
    return slogger


def test_params_land_in_bar_row_with_component_prefix(tmp_path):
    """Dict params of all four components land as param_{component}_{key}."""
    slogger = _open_bar_logger(tmp_path)
    stub = _make_strategy_stub(
        slogger,
        entry_rule=SimpleNamespace(params={"entry_ppo_trending_down_short_threshold": 0.45}),
        exit_rule=SimpleNamespace(params={"exit_trending_down_long_stop_mult": 1.2518}),
        risk_manager=SimpleNamespace(params={"max_drawdown_pct": 15.0}),
        position_sizer=SimpleNamespace(params={"risk_per_trade_pct": 1.9698, "printlog": False}),
    )

    BaseStrategy._log_effective_params(stub)

    bar = slogger.current_bar_data
    assert bar["param_entry_entry_ppo_trending_down_short_threshold"] == 0.45
    assert bar["param_exit_exit_trending_down_long_stop_mult"] == 1.2518
    assert bar["param_risk_max_drawdown_pct"] == 15.0
    assert bar["param_sizer_risk_per_trade_pct"] == 1.9698
    assert bar["param_sizer_printlog"] is False


def test_params_survive_finalize_to_csv(tmp_path):
    """param_* columns pass schema validation and reach the written CSV."""
    slogger = _open_bar_logger(tmp_path)
    slogger.log_strategy_state({"bar_count": 1, "datetime": "2026-06-10 15:00:00"})
    stub = _make_strategy_stub(
        slogger, exit_rule=SimpleNamespace(params={"exit_atr_period": 13})
    )

    BaseStrategy._log_effective_params(stub)
    slogger.finalize_bar()
    path = slogger.finalize_logging()

    df = pd.read_csv(path)
    assert "param_exit_exit_atr_period" in df.columns
    assert df["param_exit_exit_atr_period"].iloc[0] == 13


def test_append_mode_is_backward_safe_for_existing_csv(tmp_path):
    """Appending rows that carry NEW param_* columns must not break an existing
    CSV written before the audit hook existed (old rows get NaN)."""
    # First run: a row WITHOUT param columns (pre-hook file).
    slogger1 = _open_bar_logger(tmp_path, append_mode=True)
    slogger1.log_strategy_state({"bar_count": 1, "datetime": "2026-06-09 15:00:00"})
    slogger1.finalize_bar()
    path = slogger1.finalize_logging()

    # Second run: same file, now with param columns.
    slogger2 = _open_bar_logger(tmp_path, append_mode=True)
    slogger2.log_strategy_state({"bar_count": 2, "datetime": "2026-06-10 15:00:00"})
    stub = _make_strategy_stub(
        slogger2, entry_rule=SimpleNamespace(params={"entry_minus_di_threshold": 20.58})
    )
    BaseStrategy._log_effective_params(stub)
    slogger2.finalize_bar()
    slogger2.finalize_logging()

    df = pd.read_csv(path)
    assert len(df) == 2
    assert pd.isna(df["param_entry_entry_minus_di_threshold"].iloc[0])
    assert df["param_entry_entry_minus_di_threshold"].iloc[1] == 20.58


def test_typed_dataclass_params_are_flattened(tmp_path):
    """Components on the typed-Params surface are flattened via dataclasses.asdict."""

    @dataclass
    class Params:
        threshold: float = 0.7
        printlog: bool = False

    slogger = _open_bar_logger(tmp_path)
    stub = _make_strategy_stub(slogger, entry_rule=SimpleNamespace(params=Params()))

    BaseStrategy._log_effective_params(stub)

    assert slogger.current_bar_data["param_entry_threshold"] == 0.7


def test_non_scalar_values_are_skipped(tmp_path):
    """Lists/dicts/None are not loggable as CSV scalars and must be skipped."""
    slogger = _open_bar_logger(tmp_path)
    stub = _make_strategy_stub(
        slogger,
        entry_rule=SimpleNamespace(
            params={"good": 1.0, "bad_list": [1, 2], "bad_dict": {"a": 1}, "bad_none": None}
        ),
    )

    BaseStrategy._log_effective_params(stub)

    bar = slogger.current_bar_data
    assert bar["param_entry_good"] == 1.0
    assert "param_entry_bad_list" not in bar
    assert "param_entry_bad_dict" not in bar
    assert "param_entry_bad_none" not in bar


@pytest.mark.parametrize(
    "slogger_factory",
    [
        lambda tmp_path: None,
        lambda tmp_path: NullStrategyLogger(),
        lambda tmp_path: CSVStrategyLogger(
            output_dir=str(tmp_path), strategy_name="qmt_test", enabled=False
        ),
    ],
    ids=["no_logger", "null_logger", "disabled_logger"],
)
def test_noop_when_logger_absent_disabled_or_null(tmp_path, slogger_factory):
    """No logger / NullStrategyLogger / disabled logger -> silent no-op."""
    stub = _make_strategy_stub(
        slogger_factory(tmp_path), entry_rule=SimpleNamespace(params={"x": 1})
    )
    BaseStrategy._log_effective_params(stub)  # must not raise


def test_noop_when_bar_scope_not_open(tmp_path):
    """Before start_new_bar the row dict is empty -> no-op, no row pollution."""
    slogger = CSVStrategyLogger(
        output_dir=str(tmp_path), strategy_name="qmt_test", enabled=True
    )
    stub = _make_strategy_stub(slogger, entry_rule=SimpleNamespace(params={"x": 1}))

    BaseStrategy._log_effective_params(stub)

    assert slogger.current_bar_data == {}


def test_never_raises_even_on_hostile_components(tmp_path):
    """A component whose .params access explodes must not break the bar."""

    class Hostile:
        @property
        def params(self):
            raise RuntimeError("boom")

    slogger = _open_bar_logger(tmp_path)
    stub = _make_strategy_stub(slogger, entry_rule=Hostile())

    BaseStrategy._log_effective_params(stub)  # must not raise
