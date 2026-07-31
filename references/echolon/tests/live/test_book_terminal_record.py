"""Unit tests for book_terminal_record (factored out of
PortfolioTradingRunner._process_fills in 2026-05-08 refactor).

Exercises the three terminal-status branches against a fake slot to
prevent regressions in fill bookkeeping (the money path).
"""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echolon.live.orchestrator.portfolio import book_terminal_record
from echolon.strategy.interfaces import (
    Order, OrderIntent, OrderSide, OrderStatus, OrderType,
)


def _make_order(intent=OrderIntent.ENTRY_LONG, size=1, price=24600.0):
    return Order(
        order_id="o-1",
        symbol="al2606.SF",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        intent=intent,
        size=size,
        price=price,
        metadata={"internal_ref": "ref-1"},
    )


def _make_handle(filled_volume=1, filled_avg_price=24600.0, qmt_order_id=11111):
    h = MagicMock()
    h.seq_id = 1001
    h.qmt_order_id = qmt_order_id
    h.filled_volume = filled_volume
    h.filled_avg_price = filled_avg_price
    h.last_status_msg = ""
    return h


def _make_slot(tmp_path: Path):
    slot = MagicMock()
    slot.slot_id = "al_s1"
    slot.slot_config = MagicMock(instrument="aluminum", instrument_code="al")
    slot.todays_processed_fills = []
    slot.strategy = MagicMock(strategy_logger=MagicMock())
    slot.portfolio = MagicMock(
        get_position=lambda: MagicMock(size=1, avg_price=24600.0),
        get_unrealized_pnl=lambda: 0.0,
    )
    slot.capital_slot = MagicMock(realized_pnl=0.0)
    return slot


def _trade_execution_rows(tmp_path: Path):
    files = list((tmp_path / "slots" / "al_s1").glob("trade_executions_*.csv"))
    assert len(files) == 1
    import csv

    with open(files[0], "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_book_filled_appends_fill_record_and_logs_executed(tmp_path):
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=1, filled_avg_price=24600.0)

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
    )

    assert order.status == OrderStatus.FILLED
    assert order.filled_price == 24600.0
    assert order.filled_size == 1
    assert len(slot.todays_processed_fills) == 1
    assert slot.todays_processed_fills[0]["intent"] == "ENTRY_LONG"
    slot.strategy.strategy_logger.log_order_event.assert_called_once()
    assert slot.strategy.strategy_logger.log_order_event.call_args[0][0]["action"] == "executed"
    # Money-path safety: notify_fill MUST be called on a successful fill so
    # the slot's StrategyState top-level fields (position_symbol, position_size,
    # position_side) get updated. Regression guard.
    slot.notify_fill.assert_called_once()
    notify_kwargs = slot.notify_fill.call_args.kwargs
    assert notify_kwargs["symbol"] == "al2606.SF"
    assert notify_kwargs["side"] == "LONG"
    assert notify_kwargs["size"] == 1
    assert notify_kwargs["price"] == 24600.0


def test_book_filled_writes_computed_commission_source_when_broker_missing(tmp_path):
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=1, filled_avg_price=24600.0)

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
    )

    rows = _trade_execution_rows(tmp_path)
    assert len(rows) == 1
    # al exchange-standard per-lot commission (3.0; akshare +0.01 broker offset stripped
    # per the ratified full-panel commission authority, 2026-07-20)
    assert float(rows[0]["commission"]) == pytest.approx(3.0)
    assert rows[0]["commission_source"] == "computed"


def test_book_canceled_marks_order_and_appends_canceled_intent(tmp_path):
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=0)
    handle.last_status_msg = "broker rejected, no fill"

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="canceled", reason="quiescence_late",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
    )

    assert order.status == OrderStatus.CANCELLED
    assert len(slot.todays_processed_fills) == 1
    assert slot.todays_processed_fills[0]["intent"].startswith("CANCELED_")
    slot.strategy.strategy_logger.log_order_event.assert_called_once()
    assert slot.strategy.strategy_logger.log_order_event.call_args[0][0]["action"] == "cancelled"


def test_book_rejected_marks_order_no_fill_record(tmp_path):
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=0)

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="rejected", reason="circuit_tripped",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
    )

    assert order.status == OrderStatus.REJECTED
    # rejected branch does NOT append to todays_processed_fills
    assert len(slot.todays_processed_fills) == 0
    slot.strategy.strategy_logger.log_order_event.assert_called_once()
    assert slot.strategy.strategy_logger.log_order_event.call_args[0][0]["action"] == "rejected"


def test_book_filled_with_zero_traded_price_resolves_or_marks_unknown(tmp_path):
    """Architect-flagged regression: filled-but-no-price must mark
    PRICE_UNKNOWN and skip the VP update — never silently corrupt VP."""
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=1, filled_avg_price=0.0)

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
        resolve_fill_price=lambda order_id, slot_id: 0.0,  # injected resolver returns 0
    )

    fills = slot.todays_processed_fills
    assert len(fills) == 1
    assert fills[0]["error"] == "PRICE_UNKNOWN"
    # VP must NOT have been mutated.
    slot.notify_fill.assert_not_called()


def test_book_filled_zero_volume_returns_silently(tmp_path):
    """Equivalence regression: original `if status == 56 and traded_volume > 0`
    silently fell through when status=56 with volume=0 (no elif matched).
    The refactored helper MUST also return without booking anything."""
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=0, filled_avg_price=24600.0)

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=MagicMock(),
    )

    # No fill record, no log_order_event, no notify_fill, no status mutation.
    assert len(slot.todays_processed_fills) == 0
    slot.strategy.strategy_logger.log_order_event.assert_not_called()
    slot.notify_fill.assert_not_called()
    # Order status was not mutated to FILLED.
    assert order.status != OrderStatus.FILLED


def test_book_filled_inner_exception_is_logged_not_propagated(tmp_path):
    """Equivalence regression: original FILLED branch had an inner try/except
    around VP update + logging that logged 'VP update/logging failed' and
    swallowed the exception. The refactored helper MUST preserve this."""
    slot = _make_slot(tmp_path)
    # Make the VP-mutation step raise.
    slot.portfolio.open_position.side_effect = RuntimeError("boom")
    order = _make_order(intent=OrderIntent.ENTRY_LONG)
    handle = _make_handle(filled_volume=1, filled_avg_price=24600.0)
    log = MagicMock()

    # Should not raise out of the helper.
    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=log,
    )

    # The error message text matters for ops triage continuity.
    error_messages = [c.args[0] for c in log.error.call_args_list]
    assert any("VP update/logging failed" in m for m in error_messages)


def test_book_filled_status_unchanged_when_vp_raises(tmp_path):
    """P1.2 regression: when VP mutation raises, order.status MUST NOT
    be left at FILLED — callers using status to infer VP consistency
    would be misled by the original behavior."""
    slot = _make_slot(tmp_path)
    slot.portfolio.open_position.side_effect = RuntimeError("boom")
    order = _make_order(intent=OrderIntent.ENTRY_LONG)
    handle = _make_handle(filled_volume=1, filled_avg_price=24600.0)
    log = MagicMock()

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=log,
    )

    # Order status must NOT report FILLED when VP failed.
    assert order.status != OrderStatus.FILLED
    # And the inner-exception log message is preserved.
    error_messages = [c.args[0] for c in log.error.call_args_list]
    assert any("VP update/logging failed" in m for m in error_messages)


def test_book_filled_refuses_none_intent(tmp_path):
    """P1.1 regression: a FILLED record with no intent is a caller bug;
    refuse to book the fill (no VP mutation, no CSV row, no notify)
    and log loudly so the bug is visible."""
    slot = _make_slot(tmp_path)
    order = _make_order()
    order.intent = None  # simulate caller bug
    handle = _make_handle(filled_volume=1, filled_avg_price=24600.0)
    log = MagicMock()

    book_terminal_record(
        slot=slot, order=order, handle=handle,
        kind="filled", reason="",
        slots_dir=str(tmp_path / "slots"),
        log=log,
    )

    # Nothing booked
    assert len(slot.todays_processed_fills) == 0
    slot.notify_fill.assert_not_called()
    slot.strategy.strategy_logger.log_order_event.assert_not_called()
    # Loud error logged
    error_messages = [c.args[0] for c in log.error.call_args_list]
    assert any("no intent" in m.lower() for m in error_messages)


def test_book_rejected_inner_exception_logs_distinctly(tmp_path):
    """P1.3 regression: when save_trade_execution raises in the REJECTED
    branch, an inner try/except now catches it with a distinct error
    message ('Rejected-bookkeeping failed') so ops can tell which
    branch failed."""
    slot = _make_slot(tmp_path)
    order = _make_order()
    handle = _make_handle(filled_volume=0)
    log = MagicMock()

    with patch(
        "echolon.live.io.data_logger.save_trade_execution",
        side_effect=OSError("disk full"),
    ):
        book_terminal_record(
            slot=slot, order=order, handle=handle,
            kind="rejected", reason="",
            slots_dir=str(tmp_path / "slots"),
            log=log,
        )

    # Both messages logged: the rejection itself + the bookkeeping failure
    error_messages = [c.args[0] for c in log.error.call_args_list]
    assert any("Order rejected" in m for m in error_messages)
    assert any("Rejected-bookkeeping failed" in m for m in error_messages)
