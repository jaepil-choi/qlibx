"""`vqapr check <run-id>` proves a registered run is ready without starting it, writing nothing.

Two claims are worth testing and one is worth being careful about.

**Collecting.** `freeze` stops at the first refusal, which is right for a gate in front of a
run. `check` was asked a different question -- is this ready -- so it answers about every
independent judgment at once. The test that matters is not that it reports A failure; it is that it
reports the SECOND one too, because a verb that collects and a verb that stops look identical
until there are two things wrong.

**Not mutating.** Asserted byte-for-byte over `.vqapr/`, not claimed in a docstring. The claim
stops precisely at vqapr's own writes: `check` imports user code because `weights` and `records`
are Python, and an imported module can write anywhere.

**A registered run since record `139`.** The defects a run can carry are the ones registration
admits: a run with no instruments or a reversed period is refused at `register`, so the judgments
exercised here are the ones a registrable run can still fail -- a look-ahead, a short opening in
a long-only book, a field the dataset does not expose, a first decision before the data begins.

**The run carries its own sessions and wall time since record `148`.** A look-ahead or an early
decision is therefore declared on the run (`sessions`, `at`) rather than through an schedule and a
binding, and the judgments derive the one schedule the run fires on from exactly those keys.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.check import CODES, check
from vqapr.component.fingerprint import fingerprint_component
from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.data.verification import verify_source
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.errors import FailureSource
from vqapr.domain.wiring import Role
from vqapr.public import register_instruments
from vqapr.run.preflight.checks import JUDGMENT_CODES
from vqapr.workspace.registry import WORKSPACE_DIRECTORY, Workspace
from vqapr.workspace.run_definition import RunDefinition, RunExecution, RunFill, StrategyEntry

_SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
RUN = "probe"


def _fingerprint(root: Path) -> dict[str, str]:
    """Every byte vqapr owns under the project root, addressed by path.

    Content rather than mtime: a rewrite that produced identical bytes would be invisible to a
    timestamp check on a fast filesystem, and a rewrite that changed them is exactly what this
    must catch.
    """
    workspace = root / WORKSPACE_DIRECTORY
    if not workspace.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def _register_component(root: Path, component_id: str, kind: Role, source: Path) -> None:
    object_name = source.read_text(encoding="utf-8").split("class ", 1)[1].split("(", 1)[0]
    with Workspace.transaction(root) as t:
        t.register_component(
            ComponentRef.of(
                component_id,
                kind,
                source,
                object_name,
                fingerprint=fingerprint_component(source, kind=kind, object_name=object_name),
            )
        )


def _strategy_reading(root: Path, component_id: str, dataset_id: str, field: str) -> None:
    """Register a real, loadable strategy that reads one dataset field.

    The shipped scaffold is used rather than a hand-written class because a component that does not
    load is a different refusal, and a fixture that fails to load would make these judgments look
    dead again for a new reason.
    """
    from vqapr.agent.scaffold import render

    source = root / f"{component_id}.py"
    source.write_text(
        render(
            Role.STRATEGY_MODEL, component_id, dataset_id=dataset_id, field=field,
            lookback=3,
        ),
        encoding="utf-8",
    )
    _register_component(root, component_id, Role.STRATEGY_MODEL, source)


def _exchange(root: Path, component_id: str = "venue", access: str = "SIGNED") -> None:
    source = root / f"{component_id}.py"
    source.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,"
        f" ListingAccess.{access})}})\n",
        encoding="utf-8",
    )
    _register_component(root, component_id, Role.EXCHANGE, source)


def _venue_dataset(
    root: Path, days: tuple[date, ...] = (date(2023, 12, 1),), dataset_id: str = "my-exec"
) -> None:
    """The venue table as a dataset with an execution role (record 185); the fill is the run's.

    A REAL table since the two-clocks campaign (design §3.3): the run's trading days are the
    days this table has rows for, so the days a test wants the probe to decide on are written
    here, one 15:30 UTC row each.
    """
    exec_dir = root / dataset_id
    exec_dir.mkdir(exist_ok=True)
    rows = ",\n".join(
        f"(TIMESTAMPTZ '{day.isoformat()} 15:30:00+00', 'A', true, 100.0::DOUBLE)" for day in days
    )
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
{rows}
            ) AS t(trade_at, instrument, is_tradable, close))
            TO '{(exec_dir / "e.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    # A real table is measured through the one door (record `234`): the run that reads it asks
    # for the digest registration kept, and a hand-registered table would be refused as
    # `dataset.unverified` before the ordering judgment could look at its rows.
    source = SourceSpec.of(f"{dataset_id}-src", exec_dir)
    diagnosis, _, measured = verify_source(
        DatasetRegistration.of(
            dataset_id,
            f'{dataset_id}-src',
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "close", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        ),
        source,
    )
    diagnosis.raise_if_failed()
    with Workspace.transaction(root) as t:
        t.register_dataset(measured, source)


def _fill(fill_at: str = "15:30", dataset: str = "my-exec") -> RunExecution:
    return RunExecution(
        dataset=dataset,
        trade_price="close",
        fill=RunFill(at=datetime.fromisoformat(f"2024-01-01T{fill_at}").time()),
    )


def _definition(**overrides: object) -> RunDefinition:
    """The probe run: one strategy deciding on 2023-12-01 at 15:30 UTC, unless overridden."""
    declared: dict[str, object] = {
        "run_id": RUN,
        "writes": f"{RUN}-weights",
        "strategies": (StrategyEntry("model"),),
        "timezone": "UTC",
        "schedule": {"every": "1d", "at": time(15, 30)},
        "instruments": ("A",),
        "exchange": "venue",
        "execution": _fill(),
        "start": datetime(2023, 12, 1, tzinfo=UTC),
        "end": _SPAN[1],
        "initial_account_snapshot": AccountSnapshot(0, Decimal("1000"), {"A": Decimal("-5")}),
        "initial_account_mode": AccountMode.LONG_ONLY,
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A registered run carrying four INDEPENDENT defects registration admits.

    The strategy reads `close` from a dataset exposing only `volume` (field absent); the run
    decides at 15:30 against a fill at 15:30 (a look-ahead); its one session is 2023-12-01 while
    the data begins on 2024-01-02 (an uncovered lookback); and a long-only account opens short
    (a mode conflict). None has to be repaired before another can be judged. The look-ahead and
    the early session are the run's own `at` and `sessions` (record 148), which is why
    `_definition` carries them as defaults.
    """
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                "prices",
                "prices-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument"),
                fields={"volume": "volume"},
                field_types={"volume": "INTEGER"},
            ).with_span(*_SPAN),
            SourceSpec.of("prices-source", "prepared/prices"),
        )
    _strategy_reading(tmp_path, "model", "prices", "close")
    _exchange(tmp_path)
    _venue_dataset(tmp_path)
    # Declared so the four defects above are the ONLY findings: an undeclared roster is a fifth
    # (`roster.absent`), asked by its own judge, and tested on its own.
    register_instruments(tmp_path, {"A": "stock"})
    with Workspace.transaction(tmp_path) as t:
        t.register_run(_definition())
    return tmp_path


FOUR = {
    "execution.not_after_decision",
    "lookback.uncovered",
    "field.absent",
    "weights.mode_conflict",
}


def test_a_missing_run_is_reported_rather_than_raised(workspace: Path) -> None:
    """`check` was asked a question; an unregistered run is the answer, not an exception."""
    body = check("nope", workspace)

    assert body["ok"] is False
    assert [entry["code"] for entry in body["failures"]] == ["run.unregistered"]
    assert body["stage"] == "check"


def test_every_check_that_ran_is_named_alongside_every_one_that_could_not(
    workspace: Path,
) -> None:
    """A partial report must not look complete.

    `checked` names the full set, `passed` names what held, and `blocked` names what never ran and
    why. Without the third, a reader cannot tell a judgment that passed from one that was skipped,
    and a run whose registration could not be found would look almost clean.
    """
    body = check("absent", workspace)

    assert set(body["checked"]) == {"workspace", "run", "judgments", "preflight"}
    assert body["passed"] == ["workspace"]
    skipped_names = {entry["check"] for entry in body["skipped"]}
    assert {"judgments", "preflight"} <= skipped_names, (
        "phases that could not run must be reported as skipped, not silently omitted"
    )
    for entry in body["skipped"]:
        assert entry["blocked_by"], f"{entry['check']} is skipped for no reason, which cannot be"


def test_an_unopenable_workspace_blocks_everything_that_needs_it_and_says_so(
    tmp_path: Path,
) -> None:
    """A run cannot be looked up in a workspace that does not exist, and the report says which."""
    body = check("missing", tmp_path / "no-such-project")

    assert body["ok"] is False
    assert [entry["code"] for entry in body["failures"]] == ["workspace.missing"]
    assert {entry["check"] for entry in body["skipped"]} == {"run", "judgments", "preflight"}


def test_four_simultaneous_problems_return_four_failures_in_one_call(workspace: Path) -> None:
    """AC-C3, and the reason this verb exists.

    A verb that stopped at the first would make this four round trips, each one a full workspace
    open and re-read, and the reader would not know how many remained.
    """
    body = check(RUN, workspace)

    assert body["ok"] is False
    reported = {entry["code"] for entry in body["failures"]}
    assert reported >= FOUR, f"a judgment did not report its own defect: {sorted(reported)}"


def test_check_reads_no_file_content(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Record `234`: `check` judged the execution table by scanning it again for the schema, the
    key and the price -- 11.8 s of the sample project's `check` trace (`docs/issues/095`). Every
    fact it needs was measured at registration; what it verifies now is the file's identity."""
    from vqapr.data import verification

    scans: list[str] = []
    for name in ("describe", "describe_projection", "key_check", "span_check", "finite_check",
                 "positive_finite_when_true"):
        original = getattr(verification.scan, name)

        def counting(*args, _name=name, _original=original, **kwargs):
            scans.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(verification.scan, name, counting)

    body = check(RUN, workspace)

    assert {entry["code"] for entry in body["failures"]} >= FOUR
    assert scans == [], "check scanned a file registration had already measured"


def test_each_judgment_carries_the_fields_a_reader_acts_on(workspace: Path) -> None:
    """AC-C4. A refusal without `fix` is a diagnosis, which is what this envelope replaced."""
    for entry in check(RUN, workspace)["failures"]:
        for field in (
            "code", "status", "source", "requirement", "observed", "fix", "cause",
            "examples", "example_total",
        ):
            assert field in entry, f"{entry['code']} lost {field}"
        assert entry["fix"], f"{entry['code']} says what is wrong but not what to do"
        assert entry["status"] >= 400, f"{entry['code']} says nothing about who must act"
        assert entry["cause"]["where"], f"{entry['code']} does not say where it was decided"
        if entry["code"] in JUDGMENT_CODES:
            assert str(entry["source"]["key_path"]).startswith(f"runs.{RUN}"), (
                f"{entry['code']} does not name the run it refused, so the reader must guess"
            )


def test_repairing_one_defect_leaves_the_others_reported(workspace: Path) -> None:
    """Independence, from the other direction.

    If the judgments were secretly coupled, fixing one would change what the others report. This
    closes the short position and asserts the other three refusals survive untouched.
    """
    before = {entry["code"] for entry in check(RUN, workspace)["failures"]}
    with Workspace.transaction(workspace) as t:
        t.register_run(
            _definition(
                run_id="repaired",
                initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
            )
        )
    after = {entry["code"] for entry in check("repaired", workspace)["failures"]}

    assert "weights.mode_conflict" in before
    assert "weights.mode_conflict" not in after, "the repair was not observed"
    assert FOUR - {"weights.mode_conflict"} <= after, (
        "repairing one judgment changed what another reported, so they are not independent"
    )


def test_a_period_that_is_a_point_is_reported_and_a_real_one_across_offsets_is_accepted() -> None:
    """The period judgment compares instants, never text.

    `2024-01-02T00:00:00+09:00` sorts AFTER `2024-01-01T20:00:00+00:00` as a string while being
    five hours earlier as an instant. Compared as text, `check` refused a period `run` accepts --
    a gate contradicting the thing it gates. A registered run cannot be reversed (the definition
    refuses it) but it can be a point, and a point has no room to decide in.
    """
    from vqapr.run.preflight.checks import _judge_period

    at = FailureSource(key_path="runs.x")
    point = datetime(2024, 1, 2, tzinfo=UTC)
    definition = _definition(start=point, end=point)
    assert [failure.code for failure in _judge_period(definition, at)] == [
        "period.uncovered"
    ]

    across = _definition(
        start=datetime.fromisoformat("2024-01-01T20:00:00+00:00"),
        end=datetime.fromisoformat("2024-01-02T06:00:00+09:00"),
    )
    assert _judge_period(across, at) == [], "a valid one-hour period was refused"


def test_a_blocked_judgment_carries_its_cause_separately(workspace: Path) -> None:
    """A framework bug and a routine block must not read the same.

    `observed` is one sentence; `cause` is the structure a reader filters on, and `status` says
    whose fault it is. Without them a `KeyError` -- which almost certainly means this verb is
    wrong -- looks exactly like a `VqaprError`, which means the framework declined to answer.
    """
    import vqapr.run.preflight.checks as judgments_module

    original = judgments_module._judge_universe
    judgments_module._judge_universe = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        KeyError("a judgment read a key nobody wrote")
    )
    try:
        body = check(RUN, workspace)
    finally:
        judgments_module._judge_universe = original

    entry = next(
        item for item in body["blocked"] if item["observed"].startswith("universe could not")
    )
    assert entry["code"] == "judgment.blocked"
    assert entry["cause"]["type"] == "KeyError"
    assert entry["cause"]["message"] == "'a judgment read a key nobody wrote'"
    assert "KeyError" in entry["cause"]["traceback"]
    # The stand-in judge is defined in THIS file, so the innermost frame is not the package's:
    # 502, the way a user's own code crashing reads. The framework's own bug would be 500.
    assert entry["status"] == 502


def _judge(root: Path, definition: RunDefinition) -> list[str]:
    """Every dataset code the run's members produce, the way `judgments` dispatches them.

    One judge per member since `docs/issues/archive/077`, so this loops where it used to make one call.
    A fact of `RunFacts` is a CALL, not a value: an schedule that cannot be derived raises to the
    judge that asked, which is what makes the judgment block instead of reading as passed.
    """
    from vqapr.run.preflight.checks import _judge_member_datasets, _members
    from vqapr.run.preflight.facts import RunFacts

    space = Workspace.open(root)
    registered = {str(item.dataset_id): item for item in space.datasets}
    # Read at most once per `check` and reached by every judge that needs it
    # (`docs/issues/archive/069`, record `241`).
    facts = RunFacts(space, definition)
    return [
        failure.code
        for member in _members(definition)
        for failure in _judge_member_datasets(
            definition, member, space, registered, FailureSource(key_path="runs.x"), facts
        )
    ]


def test_the_dataset_judgments_read_the_loaded_model_not_its_reference(tmp_path: Path) -> None:
    """Three of the eight judgments were permanently dead, and looked implemented.

    `workspace.component()` returns a `ComponentRef` -- an identity, a path and a fingerprint. It
    has no `requirements` attribute at all, so reading it as `getattr(component, "requirements",
    ())` always took the fallback and the loop body never ran. Only the LOADED model knows what it
    reads. This pins the distinction, because the failure mode is invisible -- a dead judgment
    reports nothing, which is exactly what a passing judgment reports.
    """
    Workspace.create(tmp_path)
    _venue_dataset(tmp_path)  # the trading days come from the execution table (design §3.3)
    _strategy_reading(tmp_path, "model", "absent_dataset", "close")

    assert _judge(tmp_path, _definition()) == ["dataset.unregistered"]


def test_one_unregistered_dataset_is_one_failure_however_many_fields_are_read(
    tmp_path: Path,
) -> None:
    """`docs/issues/archive/056`: seven fields from one missing dataset were seven identical failures.

    `requirements()` fans a `DatasetInput` out to one requirement per field; the judgment used
    to emit per requirement. The skill promises every INDEPENDENT problem at once, and one
    registration is one problem: the fields it wanted ride along as examples.
    """
    from vqapr.agent.scaffold import render
    from vqapr.run.preflight.checks import _judge_member_datasets, _members
    from vqapr.run.preflight.facts import RunFacts

    Workspace.create(tmp_path)
    _venue_dataset(tmp_path)
    source = tmp_path / "wide.py"
    scaffold = render(
        Role.STRATEGY_MODEL, "wide", dataset_id="absent_dataset", field="close",
        lookback=3,
    )
    assert 'fields=("close",)' in scaffold
    source.write_text(
        scaffold.replace('fields=("close",)', 'fields=("close", "volume", "turnover")'),
        encoding="utf-8",
    )
    _register_component(tmp_path, "wide", Role.STRATEGY_MODEL, source)

    space = Workspace.open(tmp_path)
    registered = {str(item.dataset_id): item for item in space.datasets}
    definition = _definition().replace(strategy=StrategyEntry('wide'))
    (member,) = _members(definition)
    failures = _judge_member_datasets(
        definition,
        member,
        space,
        registered,
        FailureSource(key_path="runs.x"),
        RunFacts(space, definition),
    )

    assert [failure.code for failure in failures] == ["dataset.unregistered"]
    assert failures[0].examples == ("close", "volume", "turnover")
    assert failures[0].example_total == 3
    assert "3 field(s)" in failures[0].observed


def test_a_dataset_missing_a_field_the_model_reads_is_named(tmp_path: Path) -> None:
    """`field.absent`, reachable only once the model is loaded."""
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                "prices",
                "prices-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("instrument",),
                fields={"volume": "volume"},
                field_types={"volume": "INTEGER"},
            ).with_span(*_SPAN),
            SourceSpec.of("prices-source", "prepared/prices"),
        )
    _strategy_reading(tmp_path, "model", "prices", "close")
    # On a trading day the data covers, so the absent field is the only thing wrong.
    _venue_dataset(tmp_path, days=(date(2024, 6, 3),))

    assert _judge(tmp_path, _definition()) == ["field.absent"]


def test_a_decision_that_lands_before_its_data_begins_is_named(tmp_path: Path) -> None:
    """`lookback.uncovered`, measured at the first instant that actually READS.

    Not at the run's `start`. Nothing reads there -- `start` bounds the horizon, and the strategy
    reads at the run's sessions inside it. Measuring at `start` refused any run whose dataset's
    first observation landed after midnight, which is every intraday-stamped dataset: this
    package's own end-to-end fixture was refused by its own verb while `run` completed it
    (issue 012).
    """
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                "prices",
                "prices-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("instrument",),
                fields={"close": "close"},
                field_types={"close": "DOUBLE"},
            ).with_span(*_SPAN),
            SourceSpec.of("prices-source", "prepared/prices"),
        )
    _strategy_reading(tmp_path, "model", "prices", "close")
    begins = _SPAN[0]

    # Deciding a day BEFORE the data begins: the window really is short, and it is named. The
    # trading days are the execution table's (design §3.3), so the day is written there.
    early = begins.date().replace(day=1)
    start = datetime.combine(early, time(0), tzinfo=UTC)
    _venue_dataset(tmp_path, days=(early,))
    at_four = {"every": "1d", "at": time(4, 0)}
    assert _judge(tmp_path, _definition(start=start, schedule=at_four)) == ["lookback.uncovered"]

    # The same run, deciding on a day the data covers, is not refused -- even though `start` is
    # still earlier than the dataset's first observation. That difference is the whole fix.
    covered = date(2024, 6, 3)
    _venue_dataset(tmp_path, days=(covered,), dataset_id="my-exec-covered")
    assert (
        _judge(
            tmp_path,
            _definition(start=start, schedule=at_four, execution=_fill(dataset="my-exec-covered")),
        )
        == []
    )


def _order(root: Path, definition: RunDefinition) -> list[str]:
    """Every code the ordering judgment produces, the way `judgments` dispatches it."""
    from vqapr.run.preflight.checks import _judge_execution_ordering
    from vqapr.run.preflight.facts import RunFacts

    space = Workspace.open(root)
    return [
        failure.code
        for failure in _judge_execution_ordering(
            definition, FailureSource(key_path="runs.x"), RunFacts(space, definition)
        )
    ]


def test_an_end_between_the_last_fill_and_the_last_decision_is_answered(tmp_path: Path) -> None:
    """The ordering judgment asks about the events inside `[start, end]`, not the superset.

    A decide-after-close, fill-next-close run (`at: 16:30`, `fill.at: 15:30`) has exactly one
    correct kind of `end`: between the last day's fill and that day's decision. `derived_schedule`
    cuts on dates and keeps that day's 16:30 (`docs/issues/archive/069`); handed to
    `select_target` it broke the "decision not after end" contract, and `check` reported a 500
    `judgment.blocked` where a reader looks for problems -- for the one `end` that was right
    (`docs/issues/099`). Sliced the way preflight freezes it, the judgment answers.
    """
    Workspace.create(tmp_path)
    first, last = date(2023, 12, 1), date(2023, 12, 4)
    _venue_dataset(tmp_path, days=(first, last))
    after_close = {"every": "1d", "at": time(16, 30)}
    start = datetime.combine(first, time(0), tzinfo=UTC)

    def judged(end: datetime) -> list[str]:
        return _order(tmp_path, _definition(start=start, end=end, schedule=after_close))

    # `end` between the last fill and the last decision: the 12-01 decision fills at 12-04
    # 15:30, inside the run; the 12-04 decision lies after `end` and is not the run's.
    assert judged(datetime.combine(last, time(16, 0), tzinfo=UTC)) == []
    # `end` AT the last fill is the same run.
    assert judged(datetime.combine(last, time(15, 30), tzinfo=UTC)) == []
    # `end` after the last decision: that decision has no fill, and it is NAMED, as a 412.
    assert judged(datetime.combine(last, time(23, 59), tzinfo=UTC)) == [
        "execution.not_after_decision"
    ]


def test_the_lookback_judgment_blocks_when_it_cannot_answer(tmp_path: Path) -> None:
    """No trading days, no schedule, no answer -- and it SAYS so. No guess either.

    This test used to assert the opposite half of the same fact: that the judgment stayed silent,
    on the reasoning that registration and preflight both refuse a day source naming an
    unregistered dataset, so answering here would report one defect twice. `docs/issues/archive/077`
    established what that cost -- a silent judgment is returned as an empty result, which
    `judgments` cannot tell from "asked and found nothing", so `check` reported the run as judged
    when the question was never asked. The owner settled it on 2026-09-04: the defect is named
    twice, once as a blocked judgment and once as preflight's refusal, because they are two
    different statements.

    What has not changed is the other half: nothing is guessed. The judgment raises rather than
    inventing a first-decision instant, which is what would put this verb back in the business of
    refusing what `run` accepts.
    """
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                "prices",
                "prices-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("instrument",),
                fields={"close": "close"},
                field_types={"close": "DOUBLE"},
            ).with_span(*_SPAN),
            SourceSpec.of("prices-source", "prepared/prices"),
        )
    _strategy_reading(tmp_path, "model", "prices", "close")

    # The trading days come from the execution table (design §3.3), and no `my-exec` dataset is
    # registered here: the schedule cannot be built. Nothing is guessed, and nothing is silently
    # returned either -- it raises, and `judgments` turns that into a blocked entry.
    unanswerable = _definition()
    with pytest.raises(Exception) as refused:
        _judge(tmp_path, unanswerable)
    assert "my-exec" in str(refused.value), refused.value

    # And end to end, through the verb: blocked, not passed, and `ok` is false.
    from vqapr.run.preflight.checks import judgments

    found, blocked = judgments(unanswerable, Workspace.open(tmp_path))
    assert blocked, found
    assert {entry.observed.split(" could not answer", 1)[0] for entry in blocked} >= {
        "execution_ordering"
    }


def test_the_venue_judgment_reads_every_shipped_listing_shape(tmp_path: Path) -> None:
    """A SIGNED account against a long-only listing is a contradiction, and must be caught.

    Regression test with a specific history: the first implementation called `exchange.listing(id)`,
    which only `Academic` exposes. On a `KrxExchange` it raised, was swallowed, and the judgment
    found nothing -- indistinguishable from a pass. The second read `listings` as a sequence, which
    is Academic's shape; Krx keys a Mapping by instrument id, so it silently found nothing again.
    """
    from vqapr.run.preflight.checks import _judge_weights
    from vqapr.run.preflight.facts import RunFacts

    Workspace.create(tmp_path)
    source = tmp_path / "limited.py"
    source.write_text(
        "from vqapr.public import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=True)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    _register_component(tmp_path, "limited", Role.EXCHANGE, source)

    signed = _definition(
        instruments=("ABC",),
        exchange="limited",
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
        initial_account_mode=AccountMode.SIGNED,
    )
    judged = _judge_weights(
        signed, FailureSource(key_path="runs.x"), RunFacts(Workspace.open(tmp_path), signed)
    )

    assert [failure.code for failure in judged] == ["weights.venue_conflict"], (
        "a signed account on a long-only listing was not caught, so the judgment is a no-op"
    )
    assert "long_only" in (judged[0].observed or "")


def test_check_writes_nothing_under_the_workspace(workspace: Path) -> None:
    """AC-C1, asserted byte-for-byte rather than claimed.

    This is exactly as strong as the fingerprint and no stronger: it proves vqapr wrote nothing.
    It cannot prove an imported user module wrote nothing, and the verb's docstring says so.
    """
    before = _fingerprint(workspace)
    assert before, "the fixture must produce a workspace, or this test proves nothing"

    check(RUN, workspace)

    assert _fingerprint(workspace) == before, "check mutated the workspace"


def test_check_creates_no_workspace_where_none_existed(tmp_path: Path) -> None:
    """Checking an uninitialised directory must not initialise it.

    `Workspace.create` is what several other verbs call on the way in, and calling it here would
    turn a read-only question into the command that made the directory a project.
    """
    check(RUN, tmp_path)

    assert not (tmp_path / WORKSPACE_DIRECTORY).exists()


def test_this_verb_adds_no_second_name_for_a_defect_that_has_one(tmp_path: Path) -> None:
    """`check` is not a second judge, and the reported codes are the evidence.

    An unopenable workspace already refuses with the framework's own code. Re-coding it as one of
    this verb's own would rename a defect a reader may already have handling for, so the verb
    passes that body through untouched. Its own two codes exist only for the case with no code at
    all -- a bare framework invariant that would otherwise surface as an `unhandled` failure.
    """
    body = check("gone", tmp_path / "none")
    reported = {entry["code"] for entry in body["failures"]}

    assert reported, "the workspace judgment failed, so something must have been reported"
    assert not reported & {"run.declaration_invalid", "preflight.refused"}, (
        f"check re-coded a refusal that already had a code: {sorted(reported)}"
    )

    assert len(set(CODES)) == len(CODES)

    import inspect
    import re

    from vqapr.cli.check import SIMULATION_CODES
    from vqapr.run.preflight import checks as judgments_module
    from vqapr.run.preflight.checks import JUDGMENT_BLOCKED, JUDGMENT_CODES

    # One set, owned by the judges. `check` used to hold a hand-written copy of the codes
    # `run/preflight/checks.py` raises and pin its length here; the copy drifted when a judge was added
    # (`datamodel.output_registered`) and the pin kept certifying the stale count. Record
    # 148 closed the spec-file door: a datamodel is a `runs:` entry and its judgments
    # (`check.datamodel.*`) are made by the same phases as a strategy run's, so the
    # `check.materialize.*` codes a spec used to settle are gone rather than merged.
    assert frozenset(JUDGMENT_CODES) == SIMULATION_CODES, (
        "check must publish the judges' own list, not a copy of it"
    )
    assert len(set(JUDGMENT_CODES)) == len(JUDGMENT_CODES)
    assert not any(code.startswith("check.materialize.") for code in CODES), (
        "the materialization spec's judgment set retired with the spec file (record 148)"
    )
    assert set(CODES) == set(JUDGMENT_CODES) | {
        "run.declaration_invalid",
        "preflight.refused",
    }, "CODES must be exactly the judgment set plus the two framework-invariant codes"
    assert JUDGMENT_BLOCKED not in CODES, (
        "check reports a judgment that could not answer as blocked, never as a failure, so it "
        "cannot emit require_judged's code"
    )

    # The tuple cannot drift from the judges: every code constant spelled at module level in the
    # judgments module -- which, by construction, is the constant each judge raises through --
    # must be a member. A tenth judge added with a constant but no line in `JUDGMENT_CODES`
    # fails here rather than in a reader's handling. The codes lost their `check.` prefix with
    # record `171`, so the shape matched is `NAME = "<subject>.<detail>"`, less the blocked code.
    spelled = set(
        re.findall(r'^[A-Z_]+ = "([a-z_]+\.[a-z_.]+)"$', inspect.getsource(judgments_module), re.M)
    ) - {JUDGMENT_BLOCKED}
    assert spelled, "the regex found no codes, so it proves nothing about drift"
    published = set(JUDGMENT_CODES)
    assert spelled == published, (
        f"spelled in run/preflight/checks.py but not published: {sorted(spelled - published)}; "
        f"published but not spelled: {sorted(published - spelled)}"
    )


def test_a_run_with_one_defect_reports_it_alone_and_a_repaired_run_is_clean(
    workspace: Path,
) -> None:
    """The other direction: a run that carries nothing wrong is certified, not merely tolerated."""
    space = Workspace.open(workspace)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(
            replace(
                space.dataset("prices"),
                dataset_id="full",
                fields={"close": "close", "volume": "volume"},
                field_types={"close": "DOUBLE", "volume": "INTEGER"},
            ),
            space.source("prices-source"),
        )
    assert "field.absent" in {entry["code"] for entry in check(RUN, workspace)["failures"]}
