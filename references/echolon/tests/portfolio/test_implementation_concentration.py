from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, Constructor, ConstructorConfig
from echolon.portfolio import constructor as constructor_module


@dataclass(frozen=True)
class _View:
    date: dt.date
    bars_by_instrument: dict[str, pd.DataFrame]
    meta_by_instrument: dict[str, InstrumentMeta]

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        return self.bars_by_instrument[instrument].tail(lookback).copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self.meta_by_instrument[instrument]


def _bars(price: float) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(64)]
    return pd.DataFrame({"settle": [price] * 64}, index=dates)


def _view(*, min_order_size: float = 1.0) -> _View:
    prices = {"al": 10.0, "cu": 20.0, "zn": 25.0}
    multipliers = {"al": 10.0, "cu": 5.0, "zn": 4.0}
    sectors = {"al": "base", "cu": "base", "zn": "other"}
    return _View(
        date=dt.date(2024, 3, 4),
        bars_by_instrument={
            instrument: _bars(price) for instrument, price in prices.items()
        },
        meta_by_instrument={
            instrument: InstrumentMeta(
                instrument_id=instrument,
                sector=sectors[instrument],
                multiplier=multipliers[instrument],
                tick=1.0,
                margin_rate=0.10,
                commission=3.0,
                commission_type="per_contract",
                min_order_size=min_order_size,
            )
            for instrument in prices
        },
    )


def _book(equity_rmb: float = 1_000.0) -> BookState:
    return BookState(
        date=dt.date(2024, 3, 4),
        equity_rmb=equity_rmb,
        cash_rmb=equity_rmb,
        margin_used_rmb=0.0,
    )


def _config(**overrides: object) -> ConstructorConfig:
    values: dict[str, object] = {
        "vol_target_ann_pct": 60.0,
        "sector_caps_pct": {"base": 10.0, "other": 100.0},
        "max_margin_utilization_pct": 100.0,
        "min_abs_score_for_position": 0.0,
        "implementation_min_lots": 1.0,
    }
    values.update(overrides)
    return ConstructorConfig(**values)


def _patch_anchor_vols(monkeypatch: pytest.MonkeyPatch) -> None:
    # With equity=1,000 RMB, target=60%, |scores| sum=6, and price*multiplier=100 RMB,
    # raw lots are score/vol: al=3/2.5=1.2, cu=2/2.5=0.8, zn=1/(5/11)=2.2.
    # The 10% base-sector cap halves al/cu to the step-4 anchor {0.6, 0.4, 2.2}.
    # Dropping cu changes the score denominator to 4: raw al=1.8 and zn=3.3;
    # the same 100 RMB base cap makes al=1.0, hence exact final targets {1, 0, 3}.
    vols_by_price = {10.0: 2.5, 20.0: 2.5, 25.0: 5.0 / 11.0}
    monkeypatch.setattr(
        constructor_module,
        "_annualized_vol",
        lambda settles: vols_by_price[float(settles.iloc[-1])],
    )


def test_concentration_matches_hand_computed_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_anchor_vols(monkeypatch)

    target, record = Constructor(_config()).construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": 3.0, "cu": 2.0, "zn": 1.0},
        raw_scores={"al": {}, "cu": {}, "zn": {}},
    )

    assert target.targets == {"al": 1, "cu": 0, "zn": 3}
    assert {
        key: row.pre_round_lots for key, row in record.instruments.items()
    } == pytest.approx({"al": 1.2, "cu": 0.8, "zn": 2.2})
    assert record.instruments["cu"].caps_applied[-1] == {
        "cap": "min_lot_drop",
        "before": pytest.approx(0.4),
        "after": 0.0,
    }


def test_concentration_can_legitimately_drop_every_instrument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(constructor_module, "_annualized_vol", lambda settles: 2.0)

    target, record = Constructor(
        _config(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 100.0, "other": 100.0},
        )
    ).construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": 3.0, "cu": 2.0, "zn": 1.0},
        raw_scores={"al": {}, "cu": {}, "zn": {}},
    )

    assert target.targets == {"al": 0, "cu": 0, "zn": 0}
    drops = [
        instrument
        for instrument in ("zn", "cu", "al")
        if record.instruments[instrument].caps_applied[-1]["cap"] == "min_lot_drop"
    ]
    assert drops == ["zn", "cu", "al"]


@given(
    al_score=st.floats(
        min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
    cu_score=st.floats(
        min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
    zn_score=st.floats(
        min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=50)
def test_caps_survive_concentration(
    al_score: float,
    cu_score: float,
    zn_score: float,
) -> None:
    constructor = Constructor(
        _config(
            vol_target_ann_pct=200.0,
            sector_caps_pct={"base": 7.0, "other": 9.0},
            max_margin_utilization_pct=1.5,
        )
    )
    view = _view()
    book = _book(10_000.0)

    with patch.object(constructor_module, "_annualized_vol", return_value=0.5):
        target, _ = constructor.construct(
            view=view,
            book=book,
            blended_scores={"al": al_score, "cu": cu_score, "zn": zn_score},
            raw_scores={"al": {}, "cu": {}, "zn": {}},
        )

    risk = constructor.book_risk(view, book, target.targets)
    assert risk.margin_utilization_pct <= 1.5 + 1e-9
    assert risk.sector_gross_notional_pct.get("base", 0.0) <= 7.0 + 1e-9
    assert risk.sector_gross_notional_pct.get("other", 0.0) <= 9.0 + 1e-9


def test_concentration_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_anchor_vols(monkeypatch)
    constructor = Constructor(_config())
    kwargs = {
        "view": _view(),
        "book": _book(),
        "blended_scores": {"al": 3.0, "cu": 2.0, "zn": 1.0},
        "raw_scores": {"al": {}, "cu": {}, "zn": {}},
    }

    first_target, first_record = constructor.construct(**kwargs)
    second_target, second_record = constructor.construct(**kwargs)

    assert first_target.model_dump_json() == second_target.model_dump_json()
    assert first_record.model_dump_json() == second_record.model_dump_json()


def test_concentration_breaks_equal_score_ties_by_instrument_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(constructor_module, "_annualized_vol", lambda settles: 2.0)

    target, record = Constructor(
        _config(
            vol_target_ann_pct=24.0,
            sector_caps_pct={"base": 100.0, "other": 100.0},
        )
    ).construct(
        view=_view(),
        book=_book(),
        blended_scores={"cu": 1.0, "al": 1.0},
        raw_scores={"cu": {}, "al": {}},
    )

    assert target.targets == {"cu": 1, "al": 0}
    assert record.instruments["al"].caps_applied[-1]["cap"] == "min_lot_drop"
    assert record.instruments["cu"].caps_applied == []


def test_none_preserves_the_existing_implementation_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_anchor_vols(monkeypatch)
    common = {
        "view": _view(),
        "book": _book(),
        "blended_scores": {"al": 3.0, "cu": 2.0, "zn": 1.0},
        "raw_scores": {"al": {}, "cu": {}, "zn": {}},
    }

    omitted = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=60.0,
            sector_caps_pct={"base": 10.0, "other": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
        )
    ).construct(**common)
    explicit = Constructor(_config(implementation_min_lots=None)).construct(**common)

    assert omitted[0].model_dump_json() == explicit[0].model_dump_json()
    assert omitted[1].model_dump_json() == explicit[1].model_dump_json()
    assert omitted[0].targets == {"al": 0, "cu": 0, "zn": 2}


def test_equity_concentration_uses_whole_exchange_lots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_anchor_vols(monkeypatch)

    target, record = Constructor(_config()).construct(
        view=_view(min_order_size=100.0),
        book=_book(100_000.0),
        blended_scores={"al": 3.0, "cu": 2.0, "zn": 1.0},
        raw_scores={"al": {}, "cu": {}, "zn": {}},
    )

    assert target.targets == {"al": 100, "cu": 0, "zn": 300}
    assert all(value % 100 == 0 for value in target.targets.values())
    assert record.instruments["cu"].caps_applied[-1]["cap"] == "min_lot_drop"
