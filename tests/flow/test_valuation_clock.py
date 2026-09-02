"""A valuation occurrence marks at its own instant, not at the last decision's.

AC-M7. A run values its book where the venue published a price, and the venue publishes one every
session. Before this, `_dispatch_valuation` replayed whatever mark the Account had last committed,
so the NAV series silently inherited the DECISION cadence: a strategy that rebalances monthly
reported a monthly NAV even though its book was worth something, and knowably so, on every session
in between. Factor research measures return from that series, so the gap was not cosmetic.

The mechanism under test is a synchronous mark inside `_dispatch_valuation` resolved AT OR BEFORE
the valuation instant. Two properties make that the right mechanism and both are asserted here:

- **Direction.** `select_target` selects the first STRICTLY-LATER eligible instant, which is
  correct for an intent and wrong by exactly one instant for a valuation. On the shipped cadence
  (decide 08:00, fill 15:30, value 16:00) a strictly-later rule would bind tomorrow's fill, so NAV
  would be stamped one execution instant late along its whole length.
- **Occupancy.** `pending_accepted_intent` is a single slot. A daily valuation routed through it
  would occupy it on most days and overwrite accepted decisions, so the mark must not touch it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import duckdb
import pytest

KST = ZoneInfo("Asia/Seoul")

# Ten consecutive weekday sessions. The strategy decides on the first one only, so every later
# session is a day the old behaviour would have reported a stale, replayed mark for.
SESSIONS = tuple(date(2024, 3, 4) + timedelta(days=offset) for offset in range(5)) + tuple(
    date(2024, 3, 11) + timedelta(days=offset) for offset in range(5)
)

# The strategy is asked on the first session only. Every other session has a valuation occurrence
# and NO strategy occurrence at all, which is the case the independent clock exists for: with no
# callback there is no `Hold`, so nothing mints a `PendingValuation` and the old code had
# only the replayed committed mark to report.
DECISION_SESSIONS = SESSIONS[:1]

STRATEGIES = textwrap.dedent(
    '''
    from decimal import Decimal

    from vqapr.authoring import (
        Budget, DatasetInput, Hold, PortfolioDirection, Rebalance, RowsLookback,
        StrategyModel,
    )
    from vqapr.public import AcademicExchange, ListingAccess, TradeRule

    BUDGET = Budget(
        direction=PortfolioDirection.LONG_ONLY,
        cash_lower=Decimal(0),
        cash_upper=Decimal(1),
        target_lower=Decimal(0),
        target_upper=Decimal(1),
    )


    class MonthlyDecider(StrategyModel):
        """Buys once and then holds, so decisions and sessions cannot be confused.

        The cadence lives in `self.memory`, which the framework restores before every callback
        and snapshots after it; nothing else about `self` is promised across callbacks.
        """

        def inputs(self):
            return {
                "prices": DatasetInput(
                    dataset_id="price_daily",
                    fields=("close",),
                    lookback=RowsLookback(rows=1),
                ),
            }

        def decide(self, call):
            state = self.memory if isinstance(self.memory, dict) else {}
            observed = [
                row for row in call.read("prices") if row.values["close"] is not None
            ]
            if state.get("formed") or not observed:
                return Hold(reason="already-formed")
            self.memory = {"formed": True}
            return Rebalance(
                target_weights={"A005930": Decimal("0.5")},
                cash_weight=Decimal("0.5"),
                budget=BUDGET,
            )


    class ClockExchange(AcademicExchange):
        """Whole shares, no cost. The venue is not what this file measures."""

        def __init__(self):
            super().__init__(
                {
                    "A005930": TradeRule(
                        "A005930", Decimal(1), Decimal(1), False, ListingAccess.SIGNED
                    )
                },
                "clock-academic",
            )
    '''
)

RUNNER = textwrap.dedent(
    '''
    import sys
    from datetime import date, datetime, time
    from decimal import Decimal
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from vqapr.public import (
        AccountMode, AccountSnapshot, ComponentKind, ConstraintSet, DatasetRegistration,
        ExecutionInputRegistration, ExecutionTableSpec, FillConvention, FillSelector,
        LocalInstantDeclaration, OperationAgenda, OperationOccurrence, OperationRole,
        RunDefinition, SourceSpec, StrategyConfig, ValuationConfig, component_ref,
        preflight_run, register_agenda, register_component, register_dataset,
        register_execution_input, register_strategy_config, register_valuation_config, run,
    )

    import authored_strategies

    KST = ZoneInfo("Asia/Seoul")
    root, exec_path = Path(sys.argv[1]), Path(sys.argv[2])
    price_path = Path(sys.argv[3])
    sessions = tuple(date.fromisoformat(day) for day in sys.argv[4].split(","))
    decision_sessions = tuple(date.fromisoformat(day) for day in sys.argv[5].split(","))
    valuation_sessions = (
        tuple(date.fromisoformat(day) for day in sys.argv[6].split(","))
        if len(sys.argv) > 6
        else sessions
    )


    def agenda(agenda_id, role, at, days):
        return OperationAgenda.from_occurrences(
            agenda_id=agenda_id,
            role=role,
            timezone="Asia/Seoul",
            occurrences=tuple(
                OperationOccurrence(
                    f"{agenda_id}-{day.isoformat()}",
                    role,
                    LocalInstantDeclaration(day, at, "Asia/Seoul", 0, "+09:00"),
                )
                for day in days
            ),
            provenance="valuation clock test",
        )


    register_dataset(
        root,
        DatasetRegistration.of(
            "price_daily", "clock-observation",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("clock-observation", price_path),
    )
    register_execution_input(
        root,
        ExecutionInputRegistration.of(
            "krx-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("clock-execution", exec_path),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.NEXT_ELIGIBLE, time(15, 30), "Asia/Seoul", "close"),
        ),
    )

    strategy_ref = component_ref(
        "clock-strategy", ComponentKind.STRATEGY_MODEL,
        Path(authored_strategies.__file__).resolve(), "MonthlyDecider",
    )
    exchange_ref = component_ref(
        "clock-exchange", ComponentKind.EXCHANGE,
        Path(authored_strategies.__file__).resolve(), "ClockExchange",
    )
    for reference in (strategy_ref, exchange_ref):
        register_component(root, reference)

    register_agenda(
        root, agenda("clock-strategy", OperationRole.STRATEGY_CALLBACK, time(8, 0),
                     decision_sessions)
    )
    register_agenda(
        root, agenda("clock-valuation", OperationRole.VALUATION, time(16, 0), valuation_sessions)
    )
    strategy_config = StrategyConfig(
        strategy_ref, "clock-strategy", OperationRole.STRATEGY_CALLBACK
    )
    valuation_config = ValuationConfig("clock-valuation", OperationRole.VALUATION)
    register_strategy_config(root, strategy_config)
    register_valuation_config(root, valuation_config)

    definition = RunDefinition(
        strategy_config,
        valuation_config,
        ConstraintSet(()),
        None,
        exchange_ref,
        "krx-daily",
        datetime.combine(sessions[0], time(0, 0), tzinfo=KST),
        datetime.combine(sessions[-1], time(23, 0), tzinfo=KST),
        AccountSnapshot(0, Decimal("1000000"), {}),
        AccountMode.SIGNED,
        instruments=("A005930",),
    )

    result = run(root, preflight_run(root, definition))

    # `vqapr.account` is the framework's own NAV table. Each row is one committed mark, so the
    # distinct observed instants ARE the NAV series resolution.
    account_rows = result.final_state.recorder_rows.get("vqapr.account", ())
    for row in account_rows:
        print(
            f"NAV|{row.get('event_time')}|{row.get('observed_at')}|"
            f"{row.get('nav')}|{row.get('account_version')}|"
            f"{row.get('instrument')}|{row.get('price')}"
        )
    kinds = [entry.kind.value for entry in result.final_state.lifecycle_trace]
    accepted = kinds.count("ACCEPTED_INTENT")
    executions = sum(
        1 for trace in result.occurrences if type(trace).__name__ == "DueExecutionTrace"
    )
    print(f"SUMMARY|{accepted}|{executions}")
    '''
)


@pytest.fixture
def clock_workspace(tmp_path):
    """Daily execution prices that MOVE, so a replayed mark is distinguishable from a fresh one."""
    (tmp_path / "authored_strategies.py").write_text(STRATEGIES, encoding="utf-8")
    (tmp_path / "runner.py").write_text(RUNNER, encoding="utf-8")

    rows = ",\n".join(
        f"('A005930', TIMESTAMPTZ '{session.isoformat()} 15:30:00+09', TRUE, {72000 + n * 500}.0)"
        for n, session in enumerate(SESSIONS)
    )
    execution = tmp_path / "exec.parquet"
    # The observation the strategy declares, stamped at 07:00 so the 08:00 callback can see the
    # session it decides on. The execution table keeps its own 15:30 stamps: the two clocks are
    # separate, which is the whole subject of this file.
    observed = ",\n".join(
        f"('A005930', TIMESTAMPTZ '{session.isoformat()} 07:00:00+09', {72000 + n * 500}.0)"
        for n, session in enumerate(SESSIONS)
    )
    prices = tmp_path / "prices.parquet"
    connection = duckdb.connect()
    connection.execute(
        f"""COPY (SELECT * FROM (VALUES
        {rows}
        ) AS t(instrument, trade_at, is_tradable, close))
        TO '{execution.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.execute(
        f"""COPY (SELECT * FROM (VALUES
        {observed}
        ) AS t(instrument, available_at, close))
        TO '{prices.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.close()

    root = tmp_path / "project"
    root.mkdir()
    return tmp_path, root, execution, prices


def _run(
    clock_workspace,
    *,
    decisions: tuple[date, ...] = DECISION_SESSIONS,
    valuations: tuple[date, ...] = SESSIONS,
) -> tuple[list[dict], dict]:
    tmp_path, root, execution, prices = clock_workspace
    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "runner.py"),
            str(root),
            str(execution),
            str(prices),
            ",".join(session.isoformat() for session in SESSIONS),
            ",".join(session.isoformat() for session in decisions),
            ",".join(session.isoformat() for session in valuations),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    marks: list[dict] = []
    summary: dict = {}
    for line in result.stdout.strip().splitlines():
        if line.startswith("NAV|"):
            _, event_time, observed_at, nav, version, instrument, price = line.split("|")
            marks.append(
                {
                    "event_time": event_time,
                    "observed_at": observed_at,
                    "nav": nav,
                    "account_version": version,
                    "instrument": instrument,
                    "price": price,
                }
            )
        elif line.startswith("SUMMARY|"):
            _, intents, executions = line.split("|")
            summary = {"accepted_intents": int(intents), "executions": int(executions)}
    return marks, summary


def test_a_monthly_decider_leaves_a_nav_at_every_session(clock_workspace):
    """AC-M7. The failure this test exists to catch is the ABSENCE of a change.

    One decision, ten sessions. Before the valuation clock was independent this produced marks
    only where the decision executed; now every session the venue priced carries its own mark.
    """
    marks, summary = _run(clock_workspace)

    assert summary["accepted_intents"] == 1, "the strategy must decide exactly once"

    priced = [mark for mark in marks if mark["nav"] not in ("None", "")]
    valued_sessions = {mark["event_time"][:10] for mark in priced}

    assert len(valued_sessions) > len(DECISION_SESSIONS), (
        "the NAV series still follows the decision cadence, so the valuation clock is not "
        f"independent: valued {sorted(valued_sessions)}"
    )
    assert len(valued_sessions) >= len(SESSIONS) - 1, (
        f"only {len(valued_sessions)} of {len(SESSIONS)} sessions carry a NAV: "
        f"{sorted(valued_sessions)}"
    )


def test_every_mark_observes_a_distinct_instant(clock_workspace):
    """A replayed mark repeats an instant. An independent clock produces a new one each session.

    This is what separates "the row exists" from "the row is a new measurement", and it is the
    property a row count cannot see. The instants are compared as a SET rather than against
    `event_time`: the two are different clocks by construction, since the valuation resolves at or
    before its own instant and lands on the venue's 15:30 print, while `event_time` carries the
    08:00 occurrence that opened the session.
    """
    marks, _ = _run(clock_workspace)

    observed = [mark["observed_at"] for mark in marks if mark["observed_at"] not in ("None", "")]
    assert observed, "no mark carried an observation instant at all"
    assert len(set(observed)) >= len(SESSIONS) - 1, (
        f"{len(set(observed))} distinct observation instants across {len(SESSIONS)} sessions, "
        "so marks are being replayed rather than taken"
    )


def test_a_mark_binds_the_price_at_or_before_its_own_instant(clock_workspace):
    """Direction. The mark must bind the print that already happened, never the next one.

    The valuation occurrence is at 16:00 KST and the venue prints at 15:30 KST, so an at-or-before
    rule binds the SAME session's 15:30. A strictly-later rule -- `select_target`'s contract --
    would bind tomorrow's 15:30 instead, stamping the whole series one execution instant late.

    Only the per-instrument rows are checked, because the two row kinds carry two different
    clocks on purpose: the account-level row stamps `observed_at` with when the MARK was taken
    (the 16:00 occurrence), while an instrument row stamps when its PRICE was observed (the 15:30
    print). Collapsing them would be exactly the mislabelling this table's two columns exist to
    prevent.
    """
    marks, _ = _run(clock_workspace)

    priced_instruments = [
        mark
        for mark in marks
        if mark["price"] not in ("None", "") and mark["observed_at"] not in ("None", "")
    ]
    assert priced_instruments, "no instrument row carried both a price and an observation instant"

    for mark in priced_instruments:
        observed = datetime.fromisoformat(mark["observed_at"]).astimezone(KST)
        event = datetime.fromisoformat(mark["event_time"]).astimezone(KST)
        assert observed <= event, (
            f"price observed at {observed.isoformat()} is LATER than its occurrence "
            f"{event.isoformat()}, which is the strictly-later selector leaking into valuation"
        )
        assert (observed.hour, observed.minute) == (15, 30), (
            f"price bound {observed.isoformat()}, which is not a venue print instant"
        )


def test_nav_moves_with_the_price_between_decisions(clock_workspace):
    """The book is held throughout, and the price rises every session, so NAV must rise too.

    A replayed mark would hold NAV flat across the whole hold period. Asserting movement rather
    than mere presence is what makes this a value check and not a row count.
    """
    marks, _ = _run(clock_workspace)

    navs = [mark["nav"] for mark in marks if mark["nav"] not in ("None", "")]
    assert len(navs) >= len(SESSIONS) - 1, f"only {len(navs)} priced marks"
    assert len(set(navs)) > 1, (
        "every NAV is identical across a rising price series, which is the signature of a "
        f"replayed mark: {navs[:5]}"
    )


def test_a_sparser_valuation_clock_still_leaves_every_callback_session_valued(clock_workspace):
    """The opposite cadence ratio: decisions DAILY, valuation on a subset of sessions.

    The two cadences are independent session tuples, so this is a legal declaration and nothing
    refuses it. On a session the valuation clock does not cover, the callback's replayed row is
    still the only record of the book's value, so skipping it would lose a NAV row -- the same
    defect this step exists to fix, arriving from the other direction.

    The skip is therefore keyed on the identity of the measurement, not on a valuation agenda
    merely existing.
    """
    sparse = (SESSIONS[2], SESSIONS[7])
    marks, _ = _run(clock_workspace, decisions=SESSIONS, valuations=sparse)

    priced = [mark for mark in marks if mark["nav"] not in ("None", "")]

    # The axis that matters is the MEASUREMENT date, not the occurrence date. A callback replays
    # a mark taken at the previous execution instant, so its row is dated by `observed_at`; the
    # first session has no prior price and is legitimately unmeasured.
    measured = {mark["observed_at"][:10] for mark in priced}
    assert len(measured) >= len(SESSIONS) - 1, (
        "measurements were lost on sessions the valuation clock did not cover: "
        f"only {sorted(measured)}"
    )

    # And nothing is counted twice: one measurement instant, one row.
    instants = [mark["observed_at"] for mark in priced]
    assert len(instants) == len(set(instants)), (
        f"a measurement was recorded twice: {sorted(instants)}"
    )


def test_the_pending_identity_discriminates_by_role() -> None:
    """Two occurrences at one instant in one run must not mint the same pending identity.

    `pending_id` is the token proving a completion matches its own preparation
    (`run_state.py:346-348`, `:434-436`). The key was `run_identity|instant`, which carries no
    role, so occurrences differing only in role produced the SAME uuid5 and degraded that
    invariant from a proof to a coincidence.

    The identity is read out of `_accept_valuation` rather than re-derived here. Re-deriving both
    key shapes inside the test would assert a property of `uuid5`, not of this package, and would
    stay green if the production key lost its discriminator again.
    """
    from vqapr.flow.simulation import SimulationFlow

    instant = datetime(2024, 3, 4, 16, tzinfo=KST)
    minted = {
        role: SimulationFlow._pending_valuation_key("run-1", role, instant)
        for role in ("VALUATION", "STRATEGY_CALLBACK")
    }

    assert len(set(minted.values())) == len(minted), (
        f"two roles at one instant minted the same pending identity: {minted}"
    )
    # The instant still discriminates, so the role did not replace it.
    later = SimulationFlow._pending_valuation_key(
        "run-1", "VALUATION", instant + timedelta(days=1)
    )
    assert later != minted["VALUATION"]


def test_the_valuation_never_displaces_an_accepted_decision(clock_workspace):
    """Occupancy. A daily valuation must not evict the single pending-intent slot.

    The strategy accepts exactly one intent and the account must reach version 1 by committing
    it. If a standalone valuation had been routed through `pending_accepted_intent` -- a single
    slot holding either an `AcceptedIntent` or a `PendingValuation` -- it would have overwritten
    that intent on its own session and the fill would never have committed.

    `executions` is not the discriminator here: the Hold path legitimately mints a
    `PendingValuation` on each holding session, and each completes as a due execution, so ten
    sessions produce ten due executions with only one of them carrying a fill.
    """
    marks, summary = _run(clock_workspace)

    assert summary["accepted_intents"] == 1
    versions = {mark["account_version"] for mark in marks}
    assert "1" in versions, (
        "the account never reached version 1, so the accepted intent never committed and a "
        f"valuation displaced it in the pending slot: versions {sorted(versions)}"
    )
