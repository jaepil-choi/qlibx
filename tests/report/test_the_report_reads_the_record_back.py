"""A strategy's report is computed once, from the four tables its run recorded, and adds up.

The fixture is a record small enough to check by hand: an initial account of 1000, two names
(one long, one short), three valuations, four fills and one refusal, two decisions, two
constraints. Every number asserted below was worked on paper before the code ran, and the one
identity the whole section rests on -- per-name P&L summed over names equals the change in NAV
-- is asserted to the last digit.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.flow.record import (
    RUN_KIND,
    STRATEGY_KIND,
    RunRecordWriter,
    record_fields,
    write_run_record,
)
from vqapr.public import RunReport, StrategyReport, run_report, strategy_report
from vqapr.report import measure

SEOUL = timezone(timedelta(hours=9))
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=SEOUL)
T1 = datetime(2024, 1, 2, 15, 30, tzinfo=SEOUL)
T2 = datetime(2024, 1, 3, 15, 30, tzinfo=SEOUL)
T3 = datetime(2024, 1, 4, 15, 30, tzinfo=SEOUL)
D1 = T1.replace(hour=8)
D2 = T3.replace(hour=8)
RUN = "r"
S = "s@00000001"
T = "t@00000002"
U = "u@00000003"


def _head(at: datetime, version: int, cash: str, nav: str) -> dict[str, object]:
    return {
        "event_time": at,
        "observed_at": at,
        "instrument": "_ACCOUNT",
        "account_version": version,
        "cash": Decimal(cash),
        "nav": Decimal(nav),
        "quantity": None,
        "price": None,
    }


def _position(at: datetime, version: int, name: str, quantity: str, price: str | None):
    return {
        "event_time": at,
        "observed_at": at,
        "instrument": name,
        "account_version": version,
        "cash": None,
        "nav": None,
        "quantity": Decimal(quantity),
        "price": None if price is None else Decimal(price),
    }


def _fill(at, version, name, requested, dealt, price, cash_delta, commission, tax, reason=None):
    # Text, the way the recorder writes the fill table (`vqapr.weight` too).
    return {
        "event_time": at,
        "instrument": name,
        "kind": "stock",
        "account_version": version,
        "requested_quantity": requested,
        "dealt_quantity": dealt,
        "price": price,
        "cash_delta": cash_delta,
        "commission": commission,
        "tax": tax,
        "reason": reason,
    }


def _strategy_record(strategy_ref: str, constraints: list[dict[str, str]]) -> dict[str, object]:
    strategy_id = strategy_ref.split("@")[0]
    values: dict[str, object] = dict.fromkeys(record_fields(STRATEGY_KIND))
    values.update(
        {
            "run_id": RUN,
            "strategy_ref": strategy_ref,
            "strategy_id": strategy_id,
            "fingerprint": strategy_ref.split("@")[1] * 8,
            "component": {"component_id": strategy_id},
            "agenda": {},
            "constraints": constraints,
            "account": {},
            "tables": {},
            "contract": {},
            "source_digest": {},
            "declared_digest": "d",
            "roster": None,
            "period": {"start": T0.isoformat(), "end": T3.isoformat(), "occurrences": 3},
            "timing": {},
        }
    )
    return values


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    run: dict[str, object] = dict.fromkeys(record_fields(RUN_KIND))
    run.update(
        {
            "declared_digest": "d",
            "instruments": ["A", "B", "C"],
            "period": {"start": T0.isoformat(), "end": T3.isoformat()},
            "initial_account": {"cash": "1000", "mode": "signed", "positions": {}, "version": 0},
            "datasets": [],
            "strategies": [{"component_id": "s", "record": S}, {"component_id": "t", "record": T}],
            "datamodels": [],
        }
    )
    write_run_record(root, RUN, run)

    # `s`: long A, short B, entered before the first valuation, closed at the third.
    s = RunRecordWriter(root, RUN, S)
    s.open()
    s.append(
        "vqapr.weight",
        [
            {"event_time": D1, "instrument": "A", "weight": "0.5"},
            {"event_time": D1, "instrument": "B", "weight": "-0.1"},
        ],
    )
    s.append(
        "vqapr.fill",
        [
            _fill(T1, 1, "A", "10", "10", "50", "-501", "1", "0"),
            _fill(T1, 1, "B", "-5", "-5", "20", "99.5", "0", "0.5"),
        ],
    )
    s.append(
        "vqapr.account",
        [
            _head(T1, 1, "598.5", "998.5"),
            _position(T1, 1, "A", "10", "50"),
            _position(T1, 1, "B", "-5", "20"),
        ],
    )
    s.append(
        "vqapr.monitoring",
        [
            {
                "event_time": T1,
                "constraint": "cap",
                "passed": True,
                "measured": "0.5",
                "bound": "0.6",
                "excess": "0",
                "verdict": "held",
                "tolerance": "0.006",
                "offenders": "",
                "account_version": 1,
            },
            {
                "event_time": T1,
                "constraint": "old",
                "passed": True,
                "measured": "1",
                "bound": "1",
                "excess": "0",
                "verdict": None,
                "tolerance": None,
                "offenders": "",
                "account_version": 1,
            },
        ],
    )
    s.append(
        "vqapr.account",
        [
            _head(T2, 1, "598.5", "1058.5"),
            _position(T2, 1, "A", "10", "55"),
            _position(T2, 1, "B", "-5", "18"),
        ],
    )
    s.append(
        "vqapr.monitoring",
        [
            {
                "event_time": T2,
                "constraint": "cap",
                "passed": False,
                "measured": "0.62",
                "bound": "0.6",
                "excess": "0.02",
                "verdict": "breached",
                "tolerance": "0.006",
                "offenders": "A",
                "account_version": 1,
            },
            {
                "event_time": T2,
                "constraint": "old",
                "passed": False,
                "measured": "2",
                "bound": "1",
                "excess": "1",
                "verdict": None,
                "tolerance": None,
                "offenders": "A B",
                "account_version": 1,
            },
        ],
    )
    s.append(
        "vqapr.weight",
        [
            {"event_time": D2, "instrument": "A", "weight": "0"},
            {"event_time": D2, "instrument": "B", "weight": "0"},
        ],
    )
    s.append(
        "vqapr.fill",
        [
            _fill(T3, 2, "A", "-10", "-10", "60", "598.8", "1.2", "0"),
            _fill(T3, 2, "B", "5", "5", "19", "-95", "0", "0"),
            _fill(T3, 2, "C", "3", "0", None, "0", "0", "0", reason="no_trade"),
        ],
    )
    s.append("vqapr.account", [_head(T3, 2, "1102.3", "1102.3")])
    s.append(
        "vqapr.monitoring",
        [
            {
                "event_time": T3,
                "constraint": "cap",
                "passed": True,
                "measured": None,
                "bound": "0.6",
                "excess": None,
                "verdict": "held",
                "tolerance": "0.006",
                "offenders": "",
                "account_version": 2,
            },
            {
                "event_time": T3,
                "constraint": "old",
                "passed": True,
                "measured": "0",
                "bound": "1",
                "excess": "0",
                "verdict": None,
                "tolerance": None,
                "offenders": "",
                "account_version": 2,
            },
        ],
    )
    s.finish(_strategy_record(S, [{"component_id": "cap"}]), kind=STRATEGY_KIND)
    s.release()

    # `t`: cash only, valued from the period's start; nothing declared, nothing traded.
    t = RunRecordWriter(root, RUN, T)
    t.open()
    for at, nav in ((T0, "1000"), (T1, "1000"), (T2, "1010"), (T3, "1000")):
        t.append("vqapr.account", [_head(at, 0, nav, nav)])
    t.finish(_strategy_record(T, []), kind=STRATEGY_KIND)
    t.release()
    return root


def test_the_nav_series_starts_at_the_initial_account_when_the_first_valuation_follows_a_fill(
    store: Path,
) -> None:
    report = strategy_report(store, RUN, S)

    performance = report.performance
    assert performance.initial_nav == Decimal(1000)
    assert performance.nav.instants[0] == T0 and performance.nav.values[0] == Decimal(1000)
    assert performance.nav.values == [Decimal(v) for v in ("1000", "998.5", "1058.5", "1102.3")]
    assert performance.returns.instants == [T1, T2, T3]
    assert performance.returns.values[0] == Decimal("998.5") / Decimal(1000) - 1
    assert performance.total_return == Decimal("1102.3") / Decimal(1000) - 1
    assert performance.periods == 3
    assert performance.periods_per_year == 252
    assert performance.periods_per_year_source == "inferred"
    assert performance.positive_period_share == Decimal(2) / Decimal(3)
    assert performance.max_drawdown == Decimal("998.5") / Decimal(1000) - 1
    assert performance.max_drawdown_at == T1
    assert performance.longest_drawdown_periods == 1
    assert performance.sharpe is not None and performance.sharpe > 0
    assert [row.label for row in performance.by_year] == ["2024"]
    assert performance.by_year[0].total_return == performance.total_return
    assert [row.label for row in performance.by_month] == ["2024-01"]


def test_per_name_pnl_sums_to_the_change_in_nav_and_splits_by_side(store: Path) -> None:
    attribution = strategy_report(store, RUN, S).attribution
    assert attribution is not None

    assert attribution.instants == [T1, T2, T3]
    assert attribution.total == [Decimal("-1.5"), Decimal("60"), Decimal("43.8")]
    assert attribution.long == [Decimal("-1"), Decimal("50"), Decimal("48.8")]
    assert attribution.short == [Decimal("-0.5"), Decimal("10"), Decimal("-5")]
    assert attribution.residual == [Decimal(0)] * 3, "every name was marked at both ends"
    assert attribution.total_pnl == Decimal("102.3") == Decimal("1102.3") - Decimal(1000)
    assert attribution.long_pnl == Decimal("97.8") and attribution.short_pnl == Decimal("4.5")
    assert attribution.position_hit_rate == Decimal(3) / Decimal(6)
    assert [(e.instrument, e.pnl) for e in attribution.by_instrument] == [
        ("A", Decimal("97.8")),
        ("B", Decimal("4.5")),
    ]
    assert attribution.by_instrument[0].periods_held == 3


def test_the_book_is_the_marked_weights_at_each_valuation(store: Path) -> None:
    book = strategy_report(store, RUN, S).book
    assert book is not None

    assert book.instants == [T0, T1, T2, T3]
    assert book.held == [0, 2, 2, 0] and book.long == [0, 1, 1, 0] and book.short == [0, 1, 1, 0]
    nav = Decimal("998.5")
    assert book.long_exposure[1] == Decimal(500) / nav
    assert book.short_exposure[1] == Decimal(-100) / nav
    assert book.gross_exposure[1] == Decimal(500) / nav + Decimal(100) / nav
    assert book.net_exposure[1] == Decimal(500) / nav - Decimal(100) / nav
    assert book.cash_share[1] == Decimal("598.5") / nav
    assert book.max_weight[1] == Decimal(500) / nav
    assert book.hhi[1] == (Decimal(500) / nav) ** 2 + (Decimal(100) / nav) ** 2
    assert book.unmarked == [0, 0, 0, 0]


def test_turnover_costs_and_the_refusal_come_from_the_fill_table(store: Path) -> None:
    trading = strategy_report(store, RUN, S).trading

    assert trading.realized_turnover.instants == [T1, T2, T3]
    assert trading.realized_turnover.values == [
        Decimal(600) / Decimal(1000) / 2,
        Decimal(0),
        Decimal(695) / Decimal("1058.5") / 2,
    ]
    assert trading.intended_turnover.instants == [D1, D2]
    assert trading.intended_turnover.values == [Decimal("0.3"), Decimal("0.3")]
    assert trading.rebalances == 2 and trading.orders_per_rebalance == Decimal(5) / Decimal(2)
    assert trading.fills_outside_periods == 0, "the first day's fills belong to the first period"
    years = Decimal(3) / Decimal(252)
    assert trading.annualized_intended_turnover == Decimal("0.6") / years
    costs = trading.costs
    assert costs.commission == Decimal("2.2") and costs.tax == Decimal("0.5")
    assert costs.traded_notional == Decimal(1295)
    assert costs.basis_points_of_notional == Decimal("2.7") * 10_000 / Decimal(1295)
    assert costs.by_kind == {"stock": Decimal("2.7")}
    assert trading.fills["orders"] == 5 and trading.fills["zero_dealt"] == 1
    assert trading.fills["reasons"] == {"no_trade": 1}
    assert trading.fills["never_filled"][0]["instrument"] == "C"
    holding = trading.holding
    assert holding is not None
    assert holding.round_trips == 2 and holding.mean_periods == Decimal(2)
    assert holding.open_at_end == 0


def test_intended_is_read_against_the_first_valuation_at_or_after_the_decision(
    store: Path,
) -> None:
    intent = strategy_report(store, RUN, S).intent
    assert intent is not None

    assert intent.instants == [D1, D2] and intent.realized_at == [T1, T3]
    nav = Decimal("998.5")
    expected = abs(Decimal(500) / nav - Decimal("0.5")) + abs(Decimal(-100) / nav + Decimal("0.1"))
    assert intent.gap == [expected, Decimal(0)]
    assert intent.max_gap == expected and intent.max_gap_at == D1
    # A rose 50 -> 55 under a long weight, B fell 20 -> 18 under a short one: two hits of two.
    assert intent.weight_sign_hit_rate == Decimal(1) and intent.weights_scored == 2


def test_compliance_splits_checked_into_held_breached_and_unmeasured(store: Path) -> None:
    compliance = strategy_report(store, RUN, S).compliance
    assert compliance is not None

    cap, old = compliance.constraints
    assert cap.constraint == "cap" and cap.tolerance_judged is True
    assert (cap.checked, cap.held, cap.within_tolerance, cap.breached, cap.unmeasured) == (
        3,
        1,
        0,
        1,
        1,
    )
    assert cap.breach_share == Decimal(1) / Decimal(3)
    assert cap.worst_excess == Decimal("0.02") and cap.worst_excess_at == T2
    assert [(o.instrument, o.findings) for o in cap.offenders] == [("A", 1)]
    # Written before the framework's verdict existed: the author's `passed` is all there is.
    assert old.tolerance_judged is False
    assert (old.held, old.breached, old.unmeasured) == (2, 1, 0)
    assert [(o.instrument, o.findings) for o in old.offenders] == [("A", 1), ("B", 1)]
    assert compliance.instants == [T1, T2, T3] and compliance.breached == [0, 2, 0]


def test_a_book_recorded_without_positions_says_which_sections_it_cannot_give(
    store: Path,
) -> None:
    writer = RunRecordWriter(store, RUN, U)
    writer.open()
    writer.append("vqapr.fill", [_fill(T1, 1, "A", "10", "10", "50", "-500", "0", "0")])
    writer.append("vqapr.account", [_head(T1, 1, "500", "1000"), _head(T2, 1, "500", "1100")])
    writer.finish(_strategy_record(U, []), kind=STRATEGY_KIND)
    writer.release()

    report = strategy_report(store, RUN, "u")

    assert report.positions_recorded is False
    assert report.book is None and report.attribution is None and report.intent is None
    assert report.trading.holding is None
    assert set(report.omitted) == {"book", "attribution", "intent", "trading.holding", "compliance"}
    assert "recorded without positions" in report.omitted["book"]
    assert "declared no constraint" in report.omitted["compliance"]
    assert report.performance.total_return == Decimal("0.1")


def test_a_cash_only_book_reports_its_nav_change_as_residual(store: Path) -> None:
    """`t` never traded and its NAV moved: no name earned it, so it stays in the residual."""
    report = strategy_report(store, RUN, "t")

    assert report.positions_recorded is True
    assert report.attribution is not None
    assert report.attribution.total == [Decimal(0)] * 3
    assert report.attribution.residual == [Decimal(0), Decimal(10), Decimal(-10)]
    assert report.book is not None and report.book.held == [0, 0, 0, 0]
    assert report.trading.rebalances == 0 and report.trading.orders_per_rebalance is None


def test_the_run_report_lines_the_strategies_up_and_measures_one_against_another(
    store: Path,
) -> None:
    report = run_report(store, RUN, benchmark="t")

    assert isinstance(report, RunReport)
    assert list(report.strategies) == [S, T]
    assert [row.strategy_id for row in report.headline] == ["s", "t"]
    assert report.headline[0].breached == 2 and report.headline[1].breached is None
    assert report.correlation is not None
    assert report.correlation.refs == [S, T] and report.correlation.periods == 3
    assert report.correlation.values[0][0] == Decimal(1)
    assert report.correlation.values[0][1] == report.correlation.values[1][0]
    (relative,) = report.relative
    assert relative.strategy_ref == S and relative.benchmark_ref == T
    s_returns = report.strategies[S].performance.returns.values
    t_returns = report.strategies[T].performance.returns.values
    assert relative.active_return.values == [
        a - b for a, b in zip(s_returns, t_returns, strict=True)
    ]
    assert relative.information_ratio is not None


def test_the_report_is_json_with_exact_decimals_and_zoned_instants(store: Path) -> None:
    report = strategy_report(store, RUN, S, periods_per_year=12, risk_free_annual=Decimal("0.03"))

    assert isinstance(report, StrategyReport)
    assert report.performance.periods_per_year_source == "given"
    assert report.performance.risk_free_annual == Decimal("0.03")
    record = report.as_record()
    text = json.dumps(record)
    assert json.loads(text)["performance"]["nav"]["values"][1] == "998.5"
    assert json.loads(text)["performance"]["nav"]["instants"][1] == T1.isoformat()
    assert json.loads(text)["omitted"] == {}


def test_a_benchmark_outside_the_run_is_refused_by_name(store: Path) -> None:
    with pytest.raises(Exception, match="no strategy record 'index'"):
        run_report(store, RUN, benchmark="index")


def test_a_valuation_without_its_account_row_is_refused_not_read_as_zero() -> None:
    with pytest.raises(ValueError, match="no _ACCOUNT row"):
        measure.valuations([_position(T1, 1, "A", "1", "1")])


def test_an_unknown_verdict_is_refused() -> None:
    row = {"event_time": T1, "constraint": "cap", "measured": "1", "verdict": "maybe"}
    with pytest.raises(ValueError, match="unknown verdict 'maybe'"):
        measure.compliance([row])


def test_periods_per_year_follows_the_grids_spacing() -> None:
    daily = [T1 + timedelta(days=i) for i in range(10)]
    monthly = [T1 + timedelta(days=30 * i) for i in range(10)]
    weekly = [T1 + timedelta(days=7 * i) for i in range(10)]
    assert measure.infer_periods_per_year(daily) == 252
    assert measure.infer_periods_per_year(weekly) == 52
    assert measure.infer_periods_per_year(monthly) == 12
    assert measure.infer_periods_per_year([T1]) == 252
