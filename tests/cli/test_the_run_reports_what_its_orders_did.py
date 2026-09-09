"""`run.complete` says what the orders did, not only that the simulation executed.

`docs/issues/archive/039`. A market-neutral run returned `{"ok": true, "occurrences": 732,
"account_version": 244}`. Its long side landed on 0.500 at every rebalance; its short side never
did, and by December the book carried **+9.1% of NAV in unintended net long exposure** -- a strategy
whose whole premise is neutrality running a material directional bet.

The cause was faithful market friction: names not tradable at the fill instant, skewed toward what a
reversal signal wants to short. It was correctly modelled and correctly labelled -- 1,481 of 47,318
fill rows carried `reason: nontradable`. **Nothing aggregated them.** The reporter's own summary:

> `ok: true` on this run means "the simulation executed", and I had been reading it as "the book I
> declared is the book that was held". Those differ by nine percent of NAV.

The follow-up made the case stronger rather than weaker. Most of the gap turned out to be a bug in
the reporter's own model, and the signal that would have exposed it on day one was a 3.1% zero-dealt
rate against a 1.2% baseline -- a comparison nobody could make, because no number was reported.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from vqapr.analysis.execution import fill_summary
from vqapr.flow.strategy.context import FRAMEWORK_TABLES
from vqapr.flow.engine.run_state import AcceptedRunState
from vqapr.flow.strategy.loop import SimulationResult


def _result(*tables: tuple[str, tuple[dict[str, object], ...]]) -> SimpleNamespace:
    """A stand-in shaped like the real thing: rows hang off `final_state.recorder_rows`."""
    return SimpleNamespace(final_state=SimpleNamespace(recorder_rows=dict(tables)))


def _fill(
    *, requested: str, dealt: str, reason: str | None = None
) -> dict[str, object]:
    return {
        "instrument": "A005930",
        "requested_quantity": requested,
        "dealt_quantity": dealt,
        "reason": reason,
    }


def test_the_reporters_run_would_have_named_its_own_cause() -> None:
    """The shape of the run that filed this issue, in miniature."""
    rows = (
        *(_fill(requested="10", dealt="10") for _ in range(6)),
        *(_fill(requested="-10", dealt="0", reason="nontradable") for _ in range(3)),
        _fill(requested="5", dealt="0", reason="no_trade"),
    )

    summary = fill_summary(rows)

    assert summary == {
        "orders": 10,
        "dealt": 6,
        "partial": 0,
        "zero_dealt": 4,
        "reasons": {"no_trade": 1, "nontradable": 3},
        "never_filled": [],
    }


def test_a_short_fill_is_counted_as_partial_rather_than_dealt_and_forgotten() -> None:
    """1,404 of that run's short requests were under-filled: the same gap, one degree quieter."""
    rows = (
        _fill(requested="100", dealt="100"),
        _fill(requested="-100", dealt="-40"),
        _fill(requested="50", dealt="0", reason="unfunded"),
    )

    summary = fill_summary(rows)

    assert summary["dealt"] == 2, "a partial fill did deal something, so it counts as dealt"
    assert summary["partial"] == 1, "and it is also named, because it did not deal what was asked"
    assert summary["zero_dealt"] == 1
    assert summary["reasons"] == {"unfunded": 1}


def test_reasons_stay_separate_because_they_are_not_one_fact() -> None:
    """`unfunded` is the account's own doing; the other three are the market's.

    A reader asking what the market refused them must not be handed their own empty purse in the
    same number -- which is why `ZeroDealtReason` names it separately in the first place.
    """
    rows = (
        _fill(requested="1", dealt="0", reason="absent"),
        _fill(requested="1", dealt="0", reason="nontradable"),
        _fill(requested="1", dealt="0", reason="unfunded"),
    )

    summary = fill_summary(rows)

    assert summary["reasons"] == {"absent": 1, "nontradable": 1, "unfunded": 1}


def test_a_name_that_never_filled_once_is_named_rather_than_folded_into_absent() -> None:
    """`docs/issues/archive/085`. A 20% ETF sleeve was in the run's instruments, the listing and the
    roster, and missing from the execution input's price table. Every one of 82 rebalances
    ordered it and every fill dealt zero -- correct -- and the summary said `absent: 82` beside
    `ok: true`, a number that cannot be told apart from one missing row on each of 82 names.
    The reporter found it thirty minutes later, from a -4.45%p shortfall that matched 20% of
    the book sitting in cash. It is the axis `reasons` cannot see, and it is stated by name.
    """
    rows = (
        *(_fill(requested="10", dealt="10") for _ in range(82)),
        *(
            {**_fill(requested="7", dealt="0", reason="absent"), "instrument": "A069500"}
            for _ in range(82)
        ),
        # One ordinary absence on an ordinary name: market behaviour, not a configuration error.
        {**_fill(requested="1", dealt="0", reason="absent"), "instrument": "A000660"},
        {**_fill(requested="1", dealt="1"), "instrument": "A000660"},
    )

    summary = fill_summary(rows)

    assert summary["reasons"] == {"absent": 83}, "the fold this file is about, still there"
    assert summary["never_filled"] == [
        {"instrument": "A069500", "orders": 82, "dealt": 0, "reason": "absent"}
    ], "and the name that never dealt once, beside it"


def test_a_run_that_traded_nothing_reports_zeroes_rather_than_nothing() -> None:
    """A run with no fill rows is an answer, not an absent field."""
    assert fill_summary(()) == {
        "orders": 0,
        "dealt": 0,
        "partial": 0,
        "zero_dealt": 0,
        "reasons": {},
        "never_filled": [],
    }


def test_the_envelope_reads_the_shape_the_real_result_has() -> None:
    """The bug this file's helper was written to stop repeating.

    The envelope's table readers used to read `result.tables`. `SimulationResult` has no such attribute -- it
    has `occurrences` and `final_state` -- so the component-declared half of `docs/issues/archive/024`
    reported nothing in production, while its unit test passed a `SimpleNamespace(tables=...)` and
    stayed green for a week. Both envelope fields now read one helper, and this pins the path that
    helper walks against the real types.
    """
    fields = {field.name for field in dataclasses.fields(SimulationResult)}

    assert "final_state" in fields
    assert "tables" not in fields, (
        "if SimulationResult ever grows a `tables` attribute, re-read `recorded` before trusting "
        "either envelope field again"
    )
    assert isinstance(AcceptedRunState.recorder_rows, property), (
        "the rows live on the run state; a rename here silently empties both fields"
    )


def test_a_table_the_model_declared_and_formed_is_reported_again() -> None:
    """`docs/issues/archive/024`'s own case, now driven through the attribute the real object has."""
    result = _result(
        ("vqapr.account", ()),
        ("vqapr.fill", ()),
        ("vqapr.weight", ()),
        ("ff3.formation", ()),
    )

    declared = [
        table for table in result.final_state.recorder_rows if table not in FRAMEWORK_TABLES
    ]
    assert declared == ["ff3.formation"]


def test_the_helper_returns_an_empty_mapping_for_a_result_that_recorded_nothing() -> None:
    """No rows is not a crash, and not a `None` the callers would have to test for."""
