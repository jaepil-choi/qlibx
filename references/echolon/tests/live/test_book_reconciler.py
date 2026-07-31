"""L1/L2 book reconciliation (ported from the slot risk overlay)."""
from __future__ import annotations

import csv
from dataclasses import dataclass

from echolon.live.book import BookReconciler


@dataclass
class _Pos:
    symbol: str
    volume: int
    direction: str


class FakeClient:
    def __init__(self, *, trade_batches=None, positions=None, fail=False):
        self.trade_batches = list(trade_batches or [])
        self.positions = positions or {}
        self.fail = fail
        self.trade_queries = 0

    def query_stock_trades(self):
        if self.fail:
            raise ConnectionError("broker gone")
        self.trade_queries += 1
        if not self.trade_batches:
            return []
        if len(self.trade_batches) == 1:
            return self.trade_batches[0]
        return self.trade_batches.pop(0)

    def get_positions(self):
        if self.fail:
            raise ConnectionError("broker gone")
        return self.positions


def _fill(order_id: str, intent: str = "ENTRY_LONG") -> dict:
    return {"qmt_order_id": order_id, "intent": intent}


def test_l1_matches_processed_fill_count_against_broker_trades(tmp_path):
    client = FakeClient(trade_batches=[[{"order_id": "11"}, {"order_id": "22"}]])
    recon = BookReconciler(log_path=tmp_path / "recon.csv", sleep=lambda _s: None)

    result = recon.verify_todays_trades(client, [_fill("11"), _fill("22")])

    assert result == {"status": "match", "processed": 2, "qmt": 2}
    assert client.trade_queries == 1


def test_l1_retries_once_for_qmt_trade_lag_then_matches(tmp_path):
    # First query sees only one of two trades (QMT history lag); the retry
    # sees both. Result must be a match and exactly one sleep must happen.
    sleeps: list[float] = []
    client = FakeClient(
        trade_batches=[
            [{"order_id": "11"}],
            [{"order_id": "11"}, {"order_id": "22"}],
        ]
    )
    recon = BookReconciler(log_path=tmp_path / "recon.csv", sleep=sleeps.append)

    result = recon.verify_todays_trades(client, [_fill("11"), _fill("22")])

    assert result == {"status": "match", "processed": 2, "qmt": 2}
    assert sleeps == [1.0]
    assert client.trade_queries == 2


def test_l1_reports_persistent_mismatch_and_ignores_canceled_fills(tmp_path):
    client = FakeClient(trade_batches=[[{"order_id": "11"}]])
    recon = BookReconciler(log_path=tmp_path / "recon.csv", sleep=lambda _s: None)

    result = recon.verify_todays_trades(
        client,
        [_fill("11"), _fill("22"), _fill("33", intent="CANCELED_ENTRY")],
    )

    assert result == {"status": "mismatch", "processed": 2, "qmt": 1}


def test_l1_broker_query_failure_is_an_explicit_error_status(tmp_path):
    recon = BookReconciler(log_path=tmp_path / "recon.csv", sleep=lambda _s: None)

    result = recon.verify_todays_trades(FakeClient(fail=True), [_fill("11")])

    assert result["status"] == "error"
    assert "broker gone" in result["error"]


def test_l2_cross_checks_signed_positions_and_strips_exchange_suffix(tmp_path):
    client = FakeClient(
        positions={
            "aa2608": _Pos(symbol="aa2608", volume=2, direction="LONG"),
            "bb2608": _Pos(symbol="bb2608", volume=2, direction="SHORT"),
        }
    )
    recon = BookReconciler(log_path=tmp_path / "recon.csv", sleep=lambda _s: None)

    results = recon.cross_check_positions(
        client,
        {"aa2608.SF": 2, "bb2608.SF": -1},
    )

    assert results["aa2608"] == {"status": "match", "book": 2.0, "qmt": 2.0}
    assert results["bb2608"] == {"status": "mismatch", "book": -1.0, "qmt": -2.0}

    log_rows = list(csv.reader((tmp_path / "recon.csv").open()))
    assert log_rows[0] == ["timestamp", "level", "key", "status", "details"]
    assert any(row[1] == "L2" and row[2] == "bb2608" and row[3] == "mismatch" for row in log_rows[1:])


def test_l2_flags_positions_the_book_does_not_know_about(tmp_path):
    client = FakeClient(
        positions={"cc2608": _Pos(symbol="cc2608", volume=1, direction="LONG")}
    )
    recon = BookReconciler(sleep=lambda _s: None)

    results = recon.cross_check_positions(client, {})

    assert results["cc2608"] == {"status": "mismatch", "book": 0.0, "qmt": 1.0}
