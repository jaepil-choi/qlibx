"""Falsifier suite for the average-correlation portfolio-vol targeting mode.

Covers the four WP-R4 falsifiers for ``ConstructorConfig.vol_model``:

  (a) FV2-SAFETY: the default (``perfect_correlation``) book is byte-identical to
      the explicit perfect-correlation book on both an equity-like and a
      futures-like fixture, and is completely inert to the new avg-correlation
      knobs. This is the proof the additive change cannot perturb any pinned book.
  (b) LIMITING CASE: on a two-name rho==1 fixture, ``avg_correlation`` reproduces
      the perfect-correlation sizing exactly.
  (c) MATH CHECK: on a two-name rho==0 fixture, deployment is ~sqrt(2) larger.
  (d) CAPS ENGAGE: a synthetic book must trip the per-name cap and renormalize.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, Constructor, ConstructorConfig


@dataclass(frozen=True)
class _View:
    date: dt.date
    bars_by_instrument: dict[str, pd.DataFrame]
    meta_by_instrument: dict[str, InstrumentMeta]

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self.bars_by_instrument[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self.meta_by_instrument[instrument]


def _bars_from_returns(
    returns: list[float], *, start_price: float, contract: str = "X"
) -> pd.DataFrame:
    prices = [start_price]
    for value in returns:
        prices.append(prices[-1] * (1.0 + value))
    dates = [dt.date(2022, 1, 3) + dt.timedelta(days=index) for index in range(len(prices))]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * len(prices),
            "open_interest": [5000] * len(prices),
            "contract": [contract] * len(prices),
            "suspended": [0.0] * len(prices),
        },
        index=dates,
    )


def _ramp_bars(start_price: float, count: int = 70) -> pd.DataFrame:
    dates = [dt.date(2022, 1, 3) + dt.timedelta(days=index) for index in range(count)]
    prices = [start_price + index for index in range(count)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * count,
            "open_interest": [5000] * count,
            "contract": ["X"] * count,
            "suspended": [0.0] * count,
        },
        index=dates,
    )


def _equity_meta(name: str) -> InstrumentMeta:
    return InstrumentMeta(
        instrument_id=name, sector="equity", multiplier=1.0, tick=0.01,
        margin_rate=1.0, commission=0.00025, commission_type="percentage",
        min_order_size=100.0, t_plus_one=True, stamp_duty_rate=0.0005,
    )


def _futures_meta(name: str, sector: str) -> InstrumentMeta:
    return InstrumentMeta(
        instrument_id=name, sector=sector, multiplier=10.0, tick=1.0,
        margin_rate=0.10, commission=3.0, commission_type="per_contract",
    )


def _book(equity: float = 1_000_000.0, date: dt.date | None = None) -> BookState:
    when = date or dt.date(2022, 4, 1)
    return BookState(date=when, equity_rmb=equity, cash_rmb=equity, margin_used_rmb=0.0)


# ---------------------------------------------------------------------------
# (a) FV2-safety: default == explicit perfect_correlation, on both fixtures,
#     and inert to the avg-correlation knobs.
# ---------------------------------------------------------------------------
def _construct(view: _View, config: ConstructorConfig, scores: dict[str, float]):
    return Constructor(config).construct(
        view=view,
        book=_book(date=view.date),
        blended_scores=scores,
        raw_scores={name: {} for name in scores},
    )


def _equity_view() -> _View:
    frames = {"a": _ramp_bars(30.0), "b": _ramp_bars(50.0), "c": _ramp_bars(70.0)}
    return _View(
        date=frames["a"].index[-1],
        bars_by_instrument=frames,
        meta_by_instrument={name: _equity_meta(name) for name in frames},
    )


def _futures_view() -> _View:
    frames = {"al": _ramp_bars(100.0), "cu": _ramp_bars(200.0), "au": _ramp_bars(400.0)}
    metas = {"al": _futures_meta("al", "base"), "cu": _futures_meta("cu", "base"),
             "au": _futures_meta("au", "metal")}
    return _View(date=frames["al"].index[-1], bars_by_instrument=frames, meta_by_instrument=metas)


def test_default_is_byte_identical_to_perfect_correlation_equity_fixture():
    view = _equity_view()
    scores = {"a": 2.0, "b": 1.0, "c": 0.5}
    default_cfg = ConstructorConfig(
        vol_target_ann_pct=12.0, sector_caps_pct={"equity": 25.0},
        max_margin_utilization_pct=100.0, min_abs_score_for_position=0.25,
        long_only=True, max_weight_per_name_pct=2.0, sizing_mode="research",
    )
    explicit_cfg = default_cfg.model_copy(update={
        "vol_model": "perfect_correlation", "avg_correlation_lookback_days": 7,
    })
    target_default, record_default = _construct(view, default_cfg, scores)
    target_explicit, record_explicit = _construct(view, explicit_cfg, scores)
    assert target_default.model_dump() == target_explicit.model_dump()
    assert record_default.model_dump() == record_explicit.model_dump()


def test_default_is_byte_identical_to_perfect_correlation_futures_fixture():
    view = _futures_view()
    scores = {"al": 1.5, "cu": -1.0, "au": 0.8}
    default_cfg = ConstructorConfig(
        vol_target_ann_pct=15.0, sector_caps_pct={"base": 40.0, "metal": 30.0},
        max_margin_utilization_pct=50.0, min_abs_score_for_position=0.1,
        long_only=False, sizing_mode="research",
    )
    explicit_cfg = default_cfg.model_copy(update={
        "vol_model": "perfect_correlation", "avg_correlation_lookback_days": 30,
    })
    target_default, record_default = _construct(view, default_cfg, scores)
    target_explicit, record_explicit = _construct(view, explicit_cfg, scores)
    assert target_default.model_dump() == target_explicit.model_dump()
    assert record_default.model_dump() == record_explicit.model_dump()


# ---------------------------------------------------------------------------
# (b) rho==1: avg_correlation reproduces perfect_correlation exactly.
# ---------------------------------------------------------------------------
def _two_name_view(returns_a: list[float], returns_b: list[float]) -> _View:
    frames = {
        "a": _bars_from_returns(returns_a, start_price=100.0),
        "b": _bars_from_returns(returns_b, start_price=100.0),
    }
    return _View(
        date=frames["a"].index[-1],
        bars_by_instrument=frames,
        meta_by_instrument={"a": _equity_meta("a"), "b": _equity_meta("b")},
    )


def test_avg_correlation_reduces_to_perfect_correlation_when_rho_is_one():
    identical = [0.01, -0.01, 0.01, -0.01]
    view = _two_name_view(identical, identical)  # perfectly correlated => rho_bar == 1
    scores = {"a": 1.0, "b": 1.0}
    perfect_cfg = ConstructorConfig(
        vol_target_ann_pct=12.0, sector_caps_pct={"equity": 100000.0},
        max_margin_utilization_pct=100000.0, min_abs_score_for_position=0.0,
        long_only=True, sizing_mode="research",
    )
    avg_cfg = perfect_cfg.model_copy(update={
        "vol_model": "avg_correlation", "avg_correlation_lookback_days": 4,
    })
    target_perfect, _ = _construct(view, perfect_cfg, scores)
    target_avg, _ = _construct(view, avg_cfg, scores)
    assert target_avg.targets == target_perfect.targets


# ---------------------------------------------------------------------------
# (c) rho==0: two equal names => sqrt(2) larger deployment.
# ---------------------------------------------------------------------------
def test_avg_correlation_scales_deployment_by_sqrt_two_at_zero_correlation():
    # Orthogonal, equal-magnitude returns over the 4-day window => rho_bar == 0.
    view = _two_name_view([0.01, 0.01, -0.01, -0.01], [0.01, -0.01, 0.01, -0.01])
    scores = {"a": 1.0, "b": 1.0}
    perfect_cfg = ConstructorConfig(
        vol_target_ann_pct=12.0, sector_caps_pct={"equity": 100000.0},
        max_margin_utilization_pct=100000.0, min_abs_score_for_position=0.0,
        long_only=True, sizing_mode="research",
    )
    avg_cfg = perfect_cfg.model_copy(update={
        "vol_model": "avg_correlation", "avg_correlation_lookback_days": 4,
    })
    target_perfect, _ = _construct(view, perfect_cfg, scores)
    target_avg, _ = _construct(view, avg_cfg, scores)
    ratio_a = target_avg.targets["a"] / target_perfect.targets["a"]
    ratio_b = target_avg.targets["b"] / target_perfect.targets["b"]
    assert ratio_a == pytest.approx(math.sqrt(2.0), rel=1e-3)
    assert ratio_b == pytest.approx(math.sqrt(2.0), rel=1e-3)


# ---------------------------------------------------------------------------
# (d) caps engage: a scaled book must trip the per-name cap and renormalize.
# ---------------------------------------------------------------------------
def test_avg_correlation_engages_per_name_cap_and_renormalizes():
    view = _two_name_view([0.01, 0.01, -0.01, -0.01], [0.01, -0.01, 0.01, -0.01])
    scores = {"a": 3.0, "b": 1.0}  # 'a' dominates and will hit the per-name cap
    avg_cfg = ConstructorConfig(
        vol_target_ann_pct=40.0, sector_caps_pct={"equity": 100000.0},
        max_margin_utilization_pct=100000.0, min_abs_score_for_position=0.0,
        long_only=True, max_weight_per_name_pct=5.0, sizing_mode="research",
        vol_model="avg_correlation", avg_correlation_lookback_days=4,
    )
    target, record = _construct(view, avg_cfg, scores)
    assert any(
        cap["cap"] == "per_name_weight"
        for cap in record.instruments["a"].caps_applied
    )
    price = float(view.bars("a", 1).iloc[-1]["settle"])
    notional_a = abs(target.targets["a"]) * price * 1.0
    assert notional_a <= 1_000_000.0 * 5.0 / 100.0 + 1e-6


if __name__ == "__main__":  # pragma: no cover
    import sys
    import pytest as _pytest

    sys.exit(_pytest.main([__file__, "-q"]))
