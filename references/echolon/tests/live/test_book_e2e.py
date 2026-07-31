"""End-to-end: verified bundle + real PanelData snapshot -> orders.

This is the echolon half of the live-parity contract: the SAME PanelData
class loads a snapshot-shaped live data dir, the bundle's strategy
rebalances on it, and the executor emits integer-lot diff orders.
"""
from __future__ import annotations

import datetime as dt

from echolon.live.book import (
    BookRiskOverlay,
    BookRunner,
    PaperPosition,
    TargetExecutor,
    load_bundle_strategy,
    load_live_panel_view,
    simulate_paper_fill,
)
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState

from ._book_fixtures import build_bundle, build_panel_snapshot


class FakeRouter:
    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.tripped_reasons: list[str] = []

    def submit_order(self, *, intent, symbol, volume, slot_id, intended_price=None):
        self.orders.append({"intent": intent, "symbol": symbol, "volume": volume})

    def trip_circuit(self, reason: str) -> None:
        self.tripped_reasons.append(reason)


def _wire(bundle_dir, router):
    runtime = load_bundle_strategy(bundle_dir)
    executor = TargetExecutor(
        router=router,
        book_id="book-1.0.0-g1",
        symbol_map={"aa": "aa2608.SF", "bb": "bb2608.SF", "cc": "cc2608.SF"},
    )
    overlay = BookRiskOverlay(max_drawdown_rmb=80_000.0, router=router)
    return runtime, BookRunner(
        book_id="book-1.0.0-g1",
        strategy=runtime.strategy,
        executor=executor,
        risk_overlay=overlay,
    )


def _book(date: dt.date, equity: float = 1_000_000.0) -> BookState:
    return BookState(
        date=date, equity_rmb=equity, cash_rmb=equity, margin_used_rmb=0.0, positions={}
    )


def test_bundle_to_orders_end_to_end_on_synthetic_panel(tmp_path):
    snapshot = build_panel_snapshot(tmp_path)
    bundle_dir = build_bundle(tmp_path)
    date = dt.date(2026, 7, 3)
    view = load_live_panel_view(snapshot, date)

    router = FakeRouter()
    runtime, runner = _wire(bundle_dir, router)
    result = runner.run_once(view=view, book=_book(date), current_lots={})

    assert result.halted is False
    assert result.target is not None
    # The constant-long signal scores +1 everywhere: every non-zero target is
    # long and every submitted order is an entry on the mapped live symbol.
    non_zero = {k: v for k, v in result.target.targets.items() if v}
    assert non_zero, "expected at least one sized position"
    assert all(lots > 0 for lots in non_zero.values())
    assert all(float(lots).is_integer() for lots in result.target.targets.values())
    assert {order.intent for order in result.orders} == {"ENTRY_LONG"}
    assert {order.volume for order in result.orders} == {
        int(lots) for lots in non_zero.values()
    }
    assert len(router.orders) == len(result.orders)
    # Rebalance record carries the raw scores for every instrument (S7).
    record = result.rebalance_record
    assert record is not None
    assert set(record.instruments) == {"aa", "bb", "cc"}
    assert record.instruments["aa"].raw_scores == {"const_long_v1": 1.0}


def test_end_to_end_is_idempotent_and_deterministic(tmp_path):
    snapshot = build_panel_snapshot(tmp_path)
    bundle_dir = build_bundle(tmp_path)
    date = dt.date(2026, 7, 3)
    view = load_live_panel_view(snapshot, date)

    first_router = FakeRouter()
    _, first_runner = _wire(bundle_dir, first_router)
    first = first_runner.run_once(view=view, book=_book(date), current_lots={})

    # Determinism: a fresh runtime over the same bundle + snapshot produces
    # identical targets.
    second_router = FakeRouter()
    _, second_runner = _wire(bundle_dir, second_router)
    second = second_runner.run_once(view=view, book=_book(date), current_lots={})
    assert first.target.targets == second.target.targets

    # Idempotence: already-at-target book submits nothing.
    third = second_runner.run_once(
        view=view,
        book=_book(date),
        current_lots={k: int(v) for k, v in first.target.targets.items()},
    )
    assert third.orders == []
    assert second_router.orders == [
        {"intent": o.intent, "symbol": o.symbol, "volume": o.volume} for o in second.orders
    ]


def test_paper_fill_matches_certified_backtest_arithmetic():
    # S11 anchor shape: 1 lot at open 19020, 3 bps slippage, tick 5 ->
    # 19020 * 3 bps = 5.706, rounded adversely to a 10-point offset.
    meta = InstrumentMeta(
        instrument_id="aa",
        sector="sector_a",
        multiplier=5.0,
        tick=5.0,
        margin_rate=0.09,
        commission=3.01,
        commission_type="per_contract",
        close_today_commission=None,
        currency="RMB",
    )
    fill = simulate_paper_fill(
        position=PaperPosition(),
        lots_delta=1,
        open_price=19020.0,
        contract="aa2608",
        meta=meta,
        slippage_bps=3.0,
        fill_date=dt.date(2026, 7, 6),
    )
    assert fill.fill_price == 19030.0
    assert fill.commission_rmb == 3.01
    assert fill.slippage_rmb == 10.0 * 1 * 5.0
    assert fill.realized_pnl_rmb == 0.0
    assert fill.position_after == PaperPosition(lots=1, avg_price=19030.0, contract="aa2608")

    # Closing the lot lower realizes the loss with the same arithmetic.
    close = simulate_paper_fill(
        position=fill.position_after,
        lots_delta=-1,
        open_price=19000.0,
        contract="aa2608",
        meta=meta,
        slippage_bps=3.0,
        fill_date=dt.date(2026, 7, 7),
    )
    assert close.fill_price == 18990.0  # sell-side offset rounds adversely to two ticks
    assert close.realized_pnl_rmb == (18990.0 - 19030.0) * 5.0
    assert close.position_after == PaperPosition()
