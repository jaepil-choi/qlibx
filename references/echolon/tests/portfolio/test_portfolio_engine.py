from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from echolon.panel.models import InstrumentMeta
from echolon.portfolio import (
    BookState,
    Combiner,
    Constructor,
    ConstructorConfig,
    PortfolioStrategy,
    PositionState,
)
from echolon.portfolio.constructor import _toward_zero_lot
from echolon.signals import ScoreVector, SignalEngine


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


def _bars(start_price: float = 100.0) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(80)]
    prices = [start_price + index for index in range(80)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * 80,
            "open_interest": [5000] * 80,
            "contract": ["T2401"] * 80,
        },
        index=dates,
    )


def _meta(instrument: str, sector: str) -> InstrumentMeta:
    return InstrumentMeta(
        instrument_id=instrument,
        sector=sector,
        multiplier=10.0,
        tick=1.0,
        margin_rate=0.10,
        commission=3.0,
        commission_type="per_contract",
        close_today_commission=None,
        currency="RMB",
    )


def _view() -> _View:
    return _View(
        date=dt.date(2024, 3, 20),
        bars_by_instrument={"al": _bars(100.0), "cu": _bars(200.0)},
        meta_by_instrument={"al": _meta("al", "base"), "cu": _meta("cu", "base")},
    )


def _equity_view(*, suspended: bool = False) -> _View:
    dates = [dt.date(2022, 10, 1) + dt.timedelta(days=index) for index in range(80)]
    frames = {"a": _bars(10.0), "b": _bars(20.0), "c": _bars(30.0)}
    for frame in frames.values():
        frame.index = dates
        frame["suspended"] = 0.0
    frames["a"].loc[dates[-1], "suspended"] = float(suspended)
    metas = {
        name: InstrumentMeta(
            instrument_id=name, sector="equity", multiplier=1.0, tick=0.01,
            margin_rate=1.0, commission=0.00025, commission_type="percentage",
            min_order_size=100.0,
        )
        for name in frames
    }
    return _View(date=dates[-1], bars_by_instrument=frames, meta_by_instrument=metas)


def _book(equity: float = 100_000.0) -> BookState:
    return BookState(date=dt.date(2024, 3, 20), equity_rmb=equity, cash_rmb=equity, margin_used_rmb=0.0)


def _book_with_position(instrument: str, lots: float, equity: float = 100_000.0) -> BookState:
    return BookState(
        date=dt.date(2024, 3, 20),
        equity_rmb=equity,
        cash_rmb=equity,
        margin_used_rmb=0.0,
        positions={
            instrument: PositionState(
                lots=lots,
                avg_price=100.0,
                contract="T2401",
                margin_rmb=0.0,
            )
        },
    )


def test_combiner_renormalizes_weights_for_missing_scores():
    vectors = [
        ScoreVector(signal_id="a", family="tsmom", date=dt.date(2024, 1, 1), scores={"al": 1.0, "cu": None}),
        ScoreVector(signal_id="b", family="carry", date=dt.date(2024, 1, 1), scores={"al": -1.0, "cu": 2.0}),
    ]

    blended = Combiner({"a": 0.25, "b": 0.75}).combine(vectors, instruments=["al", "cu"])

    assert blended == {"al": -0.5, "cu": 2.0}


def test_constructor_zero_score_book_is_flat():
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.5,
        )
    )

    target, record = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": 0.0, "cu": 0.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets == {"al": 0, "cu": 0}
    assert all(row.post_round_lots == 0 for row in record.instruments.values())


def test_equity_rounding_is_toward_zero_in_whole_lots():
    assert _toward_zero_lot(274.9, 100.0) == 200
    assert _toward_zero_lot(-274.9, 100.0) == -200


@given(value=st.floats(min_value=-1_000_000, max_value=1_000_000,
                       allow_nan=False, allow_infinity=False))
def test_equity_lot_rounding_property(value: float):
    rounded = _toward_zero_lot(value, 100.0)
    assert rounded % 100 == 0
    assert abs(rounded) <= abs(value) + 1e-9


def test_constructor_long_only_and_per_name_weight_cap():
    constructor = Constructor(ConstructorConfig(
        vol_target_ann_pct=80.0, sector_caps_pct={"equity": 100.0},
        max_margin_utilization_pct=100.0, min_abs_score_for_position=0.0,
        long_only=True, max_weight_per_name_pct=2.0,
    ))
    book = BookState(date=_equity_view().date, equity_rmb=1_000_000.0,
                     cash_rmb=1_000_000.0, margin_used_rmb=0.0)
    target, record = constructor.construct(
        view=_equity_view(), book=book,
        blended_scores={"a": 3.0, "b": 1.0, "c": -2.0},
        raw_scores={"a": {}, "b": {}, "c": {}},
    )
    assert all(lots >= 0 for lots in target.targets.values())
    risk_a = target.targets["a"] * _equity_view().bars("a", 1).iloc[-1]["settle"]
    assert risk_a <= 20_000.0
    assert any(cap["cap"] == "per_name_weight" for cap in record.instruments["a"].caps_applied)


def test_constructor_suspended_name_holds_current_position():
    view = _equity_view(suspended=True)
    book = BookState(
        date=view.date, equity_rmb=1_000_000.0, cash_rmb=1_000_000.0,
        margin_used_rmb=0.0,
        positions={"a": PositionState(lots=300, avg_price=10.0, contract="a", margin_rmb=0.0)},
    )
    constructor = Constructor(ConstructorConfig(
        vol_target_ann_pct=10.0, sector_caps_pct={"equity": 100.0},
        max_margin_utilization_pct=100.0, min_abs_score_for_position=0.0,
    ))
    target, record = constructor.construct(
        view=view, book=book, blended_scores={"a": -1.0}, raw_scores={"a": {}},
    )
    assert target.targets["a"] == 300
    assert record.instruments["a"].caps_applied[-1]["cap"] == "suspended_hold"


def test_constructor_sets_zero_when_instrument_has_no_visible_bars():
    view = _View(
        date=dt.date(2024, 3, 20),
        bars_by_instrument={"al": _bars(100.0), "cu": _bars(200.0).iloc[0:0]},
        meta_by_instrument={"al": _meta("al", "base"), "cu": _meta("cu", "base")},
    )
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, record = constructor.construct(
        view=view,
        book=_book(),
        blended_scores={"al": 1.0, "cu": 1.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets["cu"] == 0
    assert record.instruments["cu"].vol_ann == 0.0


def test_constructor_rebalance_band_holds_small_same_direction_increase():
    base = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
            sizing_mode="research",
        )
    )
    desired, _ = base.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": 1.0, "cu": 0.0},
        raw_scores={"al": {}, "cu": {}},
    )
    current = desired.targets["al"] - 0.10
    banded = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
            sizing_mode="research",
            rebalance_band_lots=0.25,
        )
    )

    target, record = banded.construct(
        view=_view(),
        book=_book_with_position("al", current),
        blended_scores={"al": 1.0, "cu": 0.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets["al"] == pytest.approx(current)
    band_record = record.instruments["al"].caps_applied[-1]
    assert band_record["cap"] == "rebalance_band_lots"
    assert band_record["before"] == pytest.approx(desired.targets["al"])
    assert band_record["after"] == pytest.approx(current)


def test_constructor_rebalance_band_does_not_block_exit():
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.5,
            sizing_mode="research",
            rebalance_band_lots=10.0,
        )
    )

    target, record = constructor.construct(
        view=_view(),
        book=_book_with_position("al", 1.0),
        blended_scores={"al": 0.1, "cu": 0.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets["al"] == 0.0
    assert record.instruments["al"].caps_applied == []


@given(
    al_score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    cu_score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_constructor_never_exceeds_margin_cap_after_rounding(al_score: float, cu_score: float):
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=80.0,
            sector_caps_pct={"base": 100.0},
            max_margin_utilization_pct=5.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, _ = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": al_score, "cu": cu_score},
        raw_scores={"al": {}, "cu": {}},
    )

    risk = constructor.book_risk(_view(), _book(), target.targets)
    assert risk.margin_utilization_pct <= 5.0 + 1e-9


@given(score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_constructor_never_exceeds_sector_cap_after_rounding(score: float):
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=80.0,
            sector_caps_pct={"base": 3.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, _ = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": score, "cu": score},
        raw_scores={"al": {}, "cu": {}},
    )

    risk = constructor.book_risk(_view(), _book(), target.targets)
    assert risk.sector_gross_notional_pct.get("base", 0.0) <= 3.0 + 1e-9


def test_portfolio_strategy_composes_engines_combiner_and_constructor():
    class FixedSignal(SignalEngine):
        signal_id = "fixed_v1"
        family = "tsmom"
        params = {}
        data_requirements = {}

        def compute(self, view):
            return ScoreVector(
                signal_id=self.signal_id,
                family=self.family,
                date=view.date,
                scores={"al": 1.0, "cu": None},
            )

    strategy = PortfolioStrategy(
        engines=[FixedSignal()],
        blend={"fixed_v1": 1.0},
        constructor_cfg=ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.0,
        ),
    )

    target, record = strategy.rebalance(_view(), _book())

    assert set(target.targets) == {"al", "cu"}
    assert target.targets["al"] > 0
    assert target.targets["cu"] == 0
    assert record.instruments["al"].raw_scores == {"fixed_v1": 1.0}
    assert record.instruments["cu"].raw_scores == {"fixed_v1": None}
