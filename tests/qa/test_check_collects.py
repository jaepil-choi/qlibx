"""Adversarial attacks on claim 2: `check` collects ALL independent failures, not just some.

Written against a version where two of these were BROKEN. They are fixed; the tests remain as the
pins that keep them fixed, and this docstring records what was actually wrong rather than the
speculation it started as.

1. **Several independent defects at once** -- `check` reports every judgment that can answer and
   caps nothing. Since record `139` the run is a registration, so the defects here are the ones
   registration admits: a look-ahead, a short opening in a long-only book, a strategy reading a
   dataset nobody registered -- and the preflight refusal that follows them.

2. **A judgment raising an unexpected exception type.** It used to propagate straight out of
   `check()`, crashing the one verb that exists in order never to crash. `judgments` now catches
   bare `Exception`, records the judgment as `blocked` with its exception type, withholds
   `judgments` from `passed`, and returns `ok: false`. The other judgments still report.

3. **Three advertised codes that could never fire.** `dataset.unregistered`,
   `field.absent` and `lookback.uncovered` read requirements off the raw `ComponentRef`
   that `workspace.component()` returns -- which has no `requirements` attribute at all, so a
   `getattr(..., ())` fallback always won and the loop body never executed. `check` now LOADS the
   component, and all three fire; this file proves the first of them end to end below.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.check import check
from vqapr.component.fingerprint import fingerprint_component
from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.data.verification import verify_source
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.wiring import Role
from vqapr.flow.declaration import judgments as judgments_module
from vqapr.public import register_instruments
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import (
    RunAgenda,
    RunDefinition,
    RunExecution,
    RunFill,
    StrategyEntry,
)

_SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    space = Workspace.create(tmp_path)
    registration = DatasetRegistration.of(
        "prices",
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    ).with_span(*_SPAN)
    with Workspace.transaction(space) as t:
        t.register_dataset(registration, SourceSpec.of("prices-source", "prepared/prices"))
    return tmp_path


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


def _run_ready(root: Path, *, short: bool, reads: str = "prices") -> str:
    """Register everything a run names, and the run, carrying the defects asked for.

    `reads` is the dataset the strategy declares; `prices` is registered and anything else is
    the unregistered-dataset defect. The run decides at 15:30 against a fill at 15:30, which is
    the look-ahead defect every run here carries.
    """
    # A REAL venue table: the run's trading days are the days it has rows for (design §3.3).
    # One day inside the run's period, printed at 15:30 KST -- the fill instant the 15:30
    # decision collides with.
    exec_dir = root / "exec"
    exec_dir.mkdir(exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            "COPY (SELECT * FROM (VALUES (TIMESTAMPTZ '2024-01-05 15:30:00+09', 'A', true, "
            "100.0::DOUBLE)) AS t(trade_at, instrument, is_tradable, close)) TO "
            f"'{(exec_dir / 'e.parquet').as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    # Measured through the one door (record `234`): the ordering judgment reads the table by
    # the digest registration kept, and a hand-registered table is `dataset.unverified`.
    exec_source = SourceSpec.of("exec-src", exec_dir)
    diagnosis, _, measured = verify_source(
        DatasetRegistration.of(
            'my-exec',
            'exec-src',
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "close", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        ),
        exec_source,
    )
    diagnosis.raise_if_failed()
    with Workspace.transaction(root) as t:
        t.register_dataset(measured, exec_source)
    source = root / "strategy.py"
    source.write_text(
        "from vqapr.public import StrategyModel, DataRequirement, RowsLookback, Hold\n\n"
        "class Strategy(StrategyModel):\n"
        "    def requirements(self):\n"
        f"        return (DataRequirement.of({reads!r}, 'close', lookback=RowsLookback(6)),)\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='qa probe')\n",
        encoding="utf-8",
    )
    _register_component(root, "my-strat", Role.STRATEGY_MODEL, source)
    venue = root / "venue.py"
    venue.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,"
        " ListingAccess.SIGNED)})\n",
        encoding="utf-8",
    )
    _register_component(root, "venue", Role.EXCHANGE, venue)
    # Declared, so preflight reaches the refusal this fixture is built for rather than stopping
    # at `roster.absent` -- which is a judgment code, and this test counts the non-judgment one.
    register_instruments(root, {"A": "stock"})
    with Workspace.transaction(root) as t:
        t.register_run(
            RunDefinition(
                run_id="probe",
                strategy=StrategyEntry("my-strat"),
                timezone="Asia/Seoul",
                agenda=RunAgenda(every="1d", at=(time(15, 30),)),
                instruments=("A",),
                exchange="venue",
                execution=RunExecution(
                    dataset='my-exec',
                    trade_price='close',
                    fill=RunFill(at=time(15, 30)),
                ),
                start=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
                end=datetime.fromisoformat("2024-02-01T00:00:00+00:00"),
                initial_account_snapshot=AccountSnapshot(
                    0, Decimal("1000"), {"A": Decimal("-5")} if short else {}
                ),
                initial_account_mode=AccountMode.LONG_ONLY,
                writes="probe-weights",
            )
        )
    return "probe"


def test_several_simultaneous_independent_defects_all_report(workspace: Path) -> None:
    """Independent defects, chosen so that none has to be repaired before another is judged.

    1. an execution ordering defect (the run's `at` at/after the fill's local_time)
    2. weights mode conflict (long-only account holding a short)
    3. an unregistered dataset the strategy reads
    4. preflight, which ALSO refuses -- reported as its own failure, not absorbed or dropped.

    If `check` silently capped collection anywhere -- at the first exception type it hits, or by
    short-circuiting once VqaprError classes start appearing -- this is the test that would show
    fewer than expected codes.
    """
    run_id = _run_ready(workspace, short=True, reads="absent-dataset")

    body = check(run_id, workspace)

    reported = {entry["code"] for entry in body["failures"]}
    assert {
        "execution.not_after_decision",
        "weights.mode_conflict",
        "dataset.unregistered",
    } <= reported, f"expected three independent judgments, got {sorted(reported)}"
    assert reported - set(judgments_module.JUDGMENT_CODES), (
        f"preflight ran and refused, and its refusal must be reported: {sorted(reported)}"
    )
    assert body["blocked"] == [], "every phase could run; nothing was blocked"
    assert "judgments" not in body["passed"]


def test_an_unexpected_exception_type_inside_one_judgment_is_reported_as_blocked(
    workspace: Path,
) -> None:
    """An unexpected exception type inside one judgment is reported, not propagated.

    It used to escape `check()` entirely, crashing the verb whose own docstring promises it
    "returns the envelope body rather than raising, because a refusal here is the ANSWER to the
    question asked". A judgment that could not look is never reported as one that passed.
    """
    run_id = _run_ready(workspace, short=True)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a judgment's own dependency broke in a way check does not catch")

    original = judgments_module._judge_universe
    judgments_module._judge_universe = _boom
    try:
        body = check(run_id, workspace)
    finally:
        judgments_module._judge_universe = original

    assert body["ok"] is False
    assert "judgments" not in body["passed"], (
        "a judgment that could not run was reported as passed, so a run nothing was proven "
        "about reads as clean and ready"
    )
    universe = [
        entry for entry in body["blocked"] if entry["observed"].startswith("universe could not")
    ]
    assert universe, body["blocked"]
    assert universe[0]["cause"]["type"] == "RuntimeError", universe
    assert "RuntimeError" in universe[0]["cause"]["traceback"]

    # And the other judgments still reported, which is the property this verb exists for.
    assert {entry["code"] for entry in body["failures"]} >= {"weights.mode_conflict"}


def test_the_three_dataset_codes_are_reachable_once_the_model_is_loaded(workspace: Path) -> None:
    """The three dataset judgments are reachable now that the component is loaded.

    They were dead: `workspace.component()` returns a `ComponentRef`, which has no
    `requirements` attribute, so `getattr(component, "requirements", ())` always took the
    fallback and the loop never ran. The codes sat in `CODES` looking implemented. The failure
    mode is invisible by nature -- a dead judgment reports nothing, which is exactly what a
    passing judgment reports -- so this pins the distinction directly.
    """
    run_id = _run_ready(workspace, short=False, reads="totally-unregistered-dataset")

    body = check(run_id, workspace)
    codes = {entry["code"] for entry in body["failures"]}
    assert "dataset.unregistered" in codes, (
        "the dataset judgment is dead again: it is reading the ComponentRef rather than the "
        "loaded model, so the loop body never runs and the code only looks implemented"
    )

    # Direct confirmation at the unit level: the raw ComponentRef workspace.component() returns
    # has no `requirements` attribute, so the getattr default always wins.
    ref = Workspace.open(workspace).component("my-strat")
    assert not hasattr(ref, "requirements"), (
        "ComponentRef gained a requirements attribute; if that is deliberate, the judgment could "
        "read it directly, but until then loading the component is what makes it reachable"
    )
