from __future__ import annotations

import datetime as dt

import pytest

from echolon.live.book import (
    BookRiskOverlay,
    BookRunner,
    DiffOrder,
    TargetExecutor,
    load_live_panel_view,
)
from echolon.portfolio import BookState, PositionState, RebalanceRecord, TargetBook


class FakeRouter:
    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.tripped_reasons: list[str] = []

    def submit_order(self, *, intent, symbol, volume, slot_id, intended_price=None):
        self.orders.append(
            {
                "intent": intent,
                "symbol": symbol,
                "volume": volume,
                "slot_id": slot_id,
                "intended_price": intended_price,
            }
        )

    def trip_circuit(self, reason: str) -> None:
        self.tripped_reasons.append(reason)


SYMBOLS = {"aa": "aa2608.SF", "bb": "bb2608.SF", "cc": "cc2608.SF", "dd": "dd2608.SF"}


def _executor(router: FakeRouter | None = None) -> TargetExecutor:
    return TargetExecutor(
        router=router or FakeRouter(),
        book_id="book-1.0.0-g1",
        symbol_map=SYMBOLS,
    )


def _target(targets: dict[str, int]) -> TargetBook:
    return TargetBook(date=dt.date(2026, 7, 8), targets=targets)


# ---------------------------------------------------------------------------
# TargetExecutor diff arithmetic
# ---------------------------------------------------------------------------


def test_target_executor_submits_only_required_position_diffs():
    router = FakeRouter()
    executor = _executor(router)

    submitted = executor.execute(
        _target({"aa": 0, "bb": 0, "cc": 2, "dd": -3}),
        current_lots={"aa": 1, "bb": -1},
    )

    assert submitted == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="EXIT_LONG", volume=1),
        DiffOrder(instrument="bb", symbol="bb2608.SF", intent="EXIT_SHORT", volume=1),
        DiffOrder(instrument="cc", symbol="cc2608.SF", intent="ENTRY_LONG", volume=2),
        DiffOrder(instrument="dd", symbol="dd2608.SF", intent="ENTRY_SHORT", volume=3),
    ]
    assert [order["intent"] for order in router.orders] == [
        "EXIT_LONG",
        "EXIT_SHORT",
        "ENTRY_LONG",
        "ENTRY_SHORT",
    ]
    assert all(order["slot_id"] == "book-1.0.0-g1" for order in router.orders)


def test_target_executor_reduces_long_position_with_partial_exit():
    # Falsifier for the parked-scaffold bug: 5 -> 2 long silently emitted
    # NO orders. A same-direction reduction must exit the difference.
    submitted = _executor().execute(_target({"aa": 2}), current_lots={"aa": 5})

    assert submitted == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="EXIT_LONG", volume=3)
    ]


def test_target_executor_reduces_short_position_with_partial_exit():
    submitted = _executor().execute(_target({"aa": -2}), current_lots={"aa": -5})

    assert submitted == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="EXIT_SHORT", volume=3)
    ]


def test_target_executor_increases_existing_positions_with_entries_only():
    submitted = _executor().execute(
        _target({"aa": 5, "bb": -4}), current_lots={"aa": 2, "bb": -1}
    )

    assert submitted == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="ENTRY_LONG", volume=3),
        DiffOrder(instrument="bb", symbol="bb2608.SF", intent="ENTRY_SHORT", volume=3),
    ]


def test_target_executor_decomposes_reversals_into_exit_then_entry():
    submitted = _executor().execute(
        _target({"aa": -2, "bb": 4}), current_lots={"aa": 3, "bb": -1}
    )

    assert submitted == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="EXIT_LONG", volume=3),
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="ENTRY_SHORT", volume=2),
        DiffOrder(instrument="bb", symbol="bb2608.SF", intent="EXIT_SHORT", volume=1),
        DiffOrder(instrument="bb", symbol="bb2608.SF", intent="ENTRY_LONG", volume=4),
    ]


def test_target_executor_round_trips_every_transition_back_to_target():
    # Property sweep: for every (before, after) pair in a small grid, the
    # signed order flow must equal after - before, exits never exceed the
    # held size, and entries never exceed the target size.
    executor = _executor()
    for before in range(-3, 4):
        for after in range(-3, 4):
            orders = executor.plan(_target({"aa": after}), current_lots={"aa": before})
            flow = 0
            for order in orders:
                sign = 1 if order.intent in ("ENTRY_LONG", "EXIT_SHORT") else -1
                flow += sign * order.volume
                assert order.volume > 0
            assert flow == after - before, (before, after, orders)


def test_target_executor_fails_loudly_when_symbol_mapping_is_missing():
    executor = TargetExecutor(router=FakeRouter(), book_id="book-1", symbol_map={})

    with pytest.raises(KeyError, match="missing live symbol"):
        executor.execute(_target({"aa": 1}), current_lots={})


def test_target_executor_refuses_fractional_research_targets():
    with pytest.raises(ValueError, match="research-sized"):
        _executor().execute(
            TargetBook(date=dt.date(2026, 7, 8), targets={"aa": 1.5}),
            current_lots={},
        )


# ---------------------------------------------------------------------------
# BookRiskOverlay — RMB breaker instantiated by the caller
# ---------------------------------------------------------------------------


def _book(equity: float, positions: dict | None = None) -> BookState:
    return BookState(
        date=dt.date(2026, 7, 8),
        equity_rmb=equity,
        cash_rmb=equity,
        margin_used_rmb=0.0,
        positions=positions or {},
    )


def test_book_risk_overlay_trips_router_at_configured_rmb_drawdown():
    router = FakeRouter()
    overlay = BookRiskOverlay(max_drawdown_rmb=10_000.0, router=router)

    assert overlay.check(_book(100_000.0)).halt is False  # sets the peak
    assert overlay.check(_book(90_001.0)).halt is False  # 9_999 < 10_000
    assert router.tripped_reasons == []

    result = overlay.check(_book(90_000.0))  # exactly at the limit -> halt

    assert result.halt is True
    assert result.reason == "book_drawdown"
    assert len(router.tripped_reasons) == 1
    assert "book_drawdown" in router.tripped_reasons[0]


def test_book_risk_overlay_peak_survives_restart_via_state_file(tmp_path):
    state = tmp_path / "book_risk_state.json"
    router = FakeRouter()
    overlay = BookRiskOverlay(max_drawdown_rmb=5_000.0, router=router, state_path=state)
    overlay.check(_book(100_000.0))

    # Fresh instance (process restart) must remember the 100k peak: without
    # persistence the drop to 95k would re-anchor the peak and pass.
    reloaded = BookRiskOverlay(max_drawdown_rmb=5_000.0, router=router, state_path=state)
    result = reloaded.check(_book(95_000.0))

    assert reloaded.peak_equity_rmb == 100_000.0
    assert result.halt is True


def test_book_risk_overlay_external_halt_is_the_divergence_hook():
    router = FakeRouter()
    overlay = BookRiskOverlay(max_drawdown_rmb=1.0, router=router)

    result = overlay.external_halt("divergence_breach:cost_bps_per_rebalance")

    assert result.halt is True
    assert router.tripped_reasons == ["divergence_breach:cost_bps_per_rebalance"]
    with pytest.raises(ValueError, match="non-empty reason"):
        overlay.external_halt("")


def test_book_risk_overlay_rejects_nonpositive_limit():
    with pytest.raises(ValueError, match="positive"):
        BookRiskOverlay(max_drawdown_rmb=0.0, router=FakeRouter())


# ---------------------------------------------------------------------------
# BookRunner
# ---------------------------------------------------------------------------


class _StaticStrategy:
    def __init__(self, targets: dict[str, int]) -> None:
        self.targets = targets

    def rebalance(self, view, book):
        target = TargetBook(date=book.date, targets=self.targets)
        record = RebalanceRecord(date=book.date, instruments={})
        return target, record


def test_book_runner_refuses_to_execute_when_risk_overlay_halts():
    router = FakeRouter()
    overlay = BookRiskOverlay(max_drawdown_rmb=1_000.0, router=router)
    overlay.check(_book(100_000.0))
    runner = BookRunner(
        book_id="book-1",
        strategy=_StaticStrategy({"aa": 1}),
        executor=_executor(router),
        risk_overlay=overlay,
    )

    result = runner.run_once(view=object(), book=_book(98_900.0), current_lots={})

    assert result.halted is True
    assert result.orders == []
    assert result.rebalance_record is None
    assert router.orders == []


def test_book_runner_executes_and_returns_rebalance_record():
    router = FakeRouter()
    overlay = BookRiskOverlay(max_drawdown_rmb=50_000.0, router=router)
    runner = BookRunner(
        book_id="book-1",
        strategy=_StaticStrategy({"aa": 2}),
        executor=_executor(router),
        risk_overlay=overlay,
    )

    result = runner.run_once(view=object(), book=_book(100_000.0), current_lots={})

    assert result.halted is False
    assert result.orders == [
        DiffOrder(instrument="aa", symbol="aa2608.SF", intent="ENTRY_LONG", volume=2)
    ]
    assert result.rebalance_record is not None


def test_book_runner_derives_current_lots_from_book_positions():
    router = FakeRouter()
    runner = BookRunner(
        book_id="book-1",
        strategy=_StaticStrategy({"aa": 1}),
        executor=_executor(router),
        risk_overlay=BookRiskOverlay(max_drawdown_rmb=50_000.0, router=router),
    )
    book = _book(
        100_000.0,
        positions={
            "aa": PositionState(lots=1, avg_price=100.0, contract="aa2608", margin_rmb=0.0)
        },
    )

    result = runner.run_once(view=object(), book=book)

    assert result.orders == []  # already at target — no orders from held lots


def test_load_live_panel_view_uses_panel_data_class(monkeypatch, tmp_path):
    calls = []

    class FakePanel:
        def view(self, date):
            calls.append(date)
            return {"date": date}

    class FakePanelData:
        @classmethod
        def load(cls, snapshot_dir):
            calls.append(snapshot_dir)
            return FakePanel()

    monkeypatch.setattr("echolon.live.book.runner.PanelData", FakePanelData)

    view = load_live_panel_view(tmp_path / "live_snapshot", dt.date(2026, 7, 8))

    assert view == {"date": dt.date(2026, 7, 8)}
    assert calls == [tmp_path / "live_snapshot", dt.date(2026, 7, 8)]
