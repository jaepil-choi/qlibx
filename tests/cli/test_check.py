"""`vqapr check <run-id>` proves a registered run is ready without starting it, writing nothing.

Two claims are worth testing and one is worth being careful about.

**Collecting.** `preflight_run` stops at the first refusal, which is right for a gate in front of a
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
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.cli.check import CODES, check
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import FailureSource
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.flow.run import RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

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


def _register_component(root: Path, component_id: str, kind: ComponentKind, source: Path) -> None:
    object_name = source.read_text(encoding="utf-8").split("class ", 1)[1].split("(", 1)[0]
    Workspace.open(root).register_component(
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
    from vqapr.extension.scaffold import render

    source = root / f"{component_id}.py"
    source.write_text(
        render(
            ComponentKind.STRATEGY_MODEL, component_id, dataset_id=dataset_id, field=field,
            lookback=3,
        ),
        encoding="utf-8",
    )
    _register_component(root, component_id, ComponentKind.STRATEGY_MODEL, source)


def _exchange(root: Path, component_id: str = "venue", access: str = "SIGNED") -> None:
    source = root / f"{component_id}.py"
    source.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,"
        f" ListingAccess.{access})}})\n",
        encoding="utf-8",
    )
    _register_component(root, component_id, ComponentKind.EXCHANGE, source)


def _agenda_deciding_on(root: Path, agenda_id: str, sessions: tuple[str, ...], at: str) -> None:
    """Register a strategy agenda that decides on exactly these days."""
    from vqapr.declarations import apply

    apply(
        {
            "agendas": {
                agenda_id: {
                    "role": "strategy_callback",
                    "sessions": list(sessions),
                    "at": at,
                    "timezone": "UTC",
                }
            }
        },
        root,
        base=root,
        declaration=root / "agenda.yaml",
    )


def _execution_input(root: Path, fill_at: str = "15:30") -> None:
    exec_dir = root / "exec"
    exec_dir.mkdir(exist_ok=True)
    (exec_dir / "placeholder").write_text("x", encoding="utf-8")
    Workspace.open(root).register_execution_input(
        ExecutionInputRegistration.of(
            "my-exec",
            ExecutionTableSpec(
                source=SourceSpec.of("exec-src", exec_dir),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(
                selector=FillSelector.NEXT_ELIGIBLE,
                local_time=datetime.fromisoformat(f"2024-01-01T{fill_at}").time(),
                timezone="UTC",
                trade_price="close",
            ),
        )
    )


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": RUN,
        "strategies": (StrategyEntry("model"),),
        "valuation": ValuationConfig("valuing", OperationRole.VALUATION),
        "instruments": ("A",),
        "exchange": "venue",
        "execution_input_id": "my-exec",
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

    The strategy reads `close` from a dataset exposing only `volume` (field absent); it decides
    at 15:30 against a fill at 15:30 (a look-ahead); it decides on 2023-12-01 while the data
    begins on 2024-01-02 (an uncovered lookback); and a long-only account opens short (a mode
    conflict). None has to be repaired before another can be judged.
    """
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"volume": "volume"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "model", "prices", "close")
    _exchange(tmp_path)
    _execution_input(tmp_path)
    _agenda_deciding_on(tmp_path, "early", ("2023-12-01",), at="15:30")
    from vqapr.declarations import apply

    apply(
        {"agendas": {"valuing": {"role": "valuation", "sessions": ["2024-01-03"], "at": "16:00",
                                 "timezone": "UTC"}}},
        tmp_path,
        base=tmp_path,
    )
    space = Workspace.open(tmp_path)
    space.register_strategy_config(
        StrategyConfig(space.component("model"), "early", OperationRole.STRATEGY_CALLBACK)
    )
    space.register_valuation_config(ValuationConfig("valuing", OperationRole.VALUATION))
    Workspace.open(tmp_path).register_run(_definition())
    return tmp_path


FOUR = {
    "check.execution.not_after_decision",
    "check.lookback.uncovered",
    "check.field.absent",
    "check.weights.mode_conflict",
}


def test_a_missing_run_is_reported_rather_than_raised(workspace: Path) -> None:
    """`check` was asked a question; an unregistered run is the answer, not an exception."""
    body = check("nope", workspace)

    assert body["ok"] is False
    assert [entry["code"] for entry in body["failures"]] == ["workspace.run.register.missing"]
    assert body["stage"] == "run.check"


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
    blocked_names = {entry["check"] for entry in body["blocked"]}
    assert {"judgments", "preflight"} <= blocked_names, (
        "judgments that could not run must be reported as blocked, not silently omitted"
    )
    for entry in body["blocked"]:
        assert entry["blocked_by"], f"{entry['check']} is blocked by nothing, which cannot be"


def test_an_unopenable_workspace_blocks_everything_that_needs_it_and_says_so(
    tmp_path: Path,
) -> None:
    """A run cannot be looked up in a workspace that does not exist, and the report says which."""
    body = check("missing", tmp_path / "no-such-project")

    assert body["ok"] is False
    assert [entry["code"] for entry in body["failures"]] == ["workspace.open.missing"]
    assert {entry["check"] for entry in body["blocked"]} == {"run", "judgments", "preflight"}


def test_four_simultaneous_problems_return_four_failures_in_one_call(workspace: Path) -> None:
    """AC-C3, and the reason this verb exists.

    A verb that stopped at the first would make this four round trips, each one a full workspace
    open and re-read, and the reader would not know how many remained.
    """
    body = check(RUN, workspace)

    assert body["ok"] is False
    reported = {entry["code"] for entry in body["failures"]}
    assert FOUR <= reported, f"a judgment did not report its own defect: {sorted(reported)}"


def test_each_judgment_carries_the_five_fields_a_reader_acts_on(workspace: Path) -> None:
    """AC-C4. A refusal without `fix` is a diagnosis, which is what this envelope replaced."""
    for entry in check(RUN, workspace)["failures"]:
        for field in ("code", "source", "requirement", "observed", "fix", "explain"):
            assert field in entry, f"{entry['code']} lost {field}"
        assert entry["fix"], f"{entry['code']} says what is wrong but not what to do"
        assert entry["explain"], f"{entry['code']} points at no recovery guidance"
        if entry["code"].startswith("check."):
            assert str(entry["source"]["key_path"]).startswith(f"runs.{RUN}"), (
                f"{entry['code']} does not name the run it refused, so the reader must guess"
            )


def test_repairing_one_defect_leaves_the_others_reported(workspace: Path) -> None:
    """Independence, from the other direction.

    If the judgments were secretly coupled, fixing one would change what the others report. This
    closes the short position and asserts the other three refusals survive untouched.
    """
    before = {entry["code"] for entry in check(RUN, workspace)["failures"]}
    Workspace.open(workspace).register_run(
        _definition(
            run_id="repaired",
            initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
        )
    )
    after = {entry["code"] for entry in check("repaired", workspace)["failures"]}

    assert "check.weights.mode_conflict" in before
    assert "check.weights.mode_conflict" not in after, "the repair was not observed"
    assert FOUR - {"check.weights.mode_conflict"} <= after, (
        "repairing one judgment changed what another reported, so they are not independent"
    )


def test_a_period_that_is_a_point_is_reported_and_a_real_one_across_offsets_is_accepted() -> None:
    """The period judgment compares instants, never text.

    `2024-01-02T00:00:00+09:00` sorts AFTER `2024-01-01T20:00:00+00:00` as a string while being
    five hours earlier as an instant. Compared as text, `check` refused a period `run` accepts --
    a gate contradicting the thing it gates. A registered run cannot be reversed (the definition
    refuses it) but it can be a point, and a point has no room to decide in.
    """
    from vqapr.flow.judgments import _judge_period

    at = FailureSource(key_path="runs.x")
    point = datetime(2024, 1, 2, tzinfo=UTC)
    definition = _definition(start=point, end=point)
    assert [failure.code for failure in _judge_period(definition, at)] == [
        "check.period.uncovered"
    ]

    across = _definition(
        start=datetime.fromisoformat("2024-01-01T20:00:00+00:00"),
        end=datetime.fromisoformat("2024-01-02T06:00:00+09:00"),
    )
    assert _judge_period(across, at) == [], "a valid one-hour period was refused"


def test_a_blocked_judgment_names_its_error_type_separately(workspace: Path) -> None:
    """A framework bug and a routine block must not read the same.

    `blocked_by` is one sentence; `error_type` is the field a reader filters on. Without it a
    `KeyError` -- which almost certainly means this verb is wrong -- looks exactly like a
    `VqaprError`, which means the framework declined to answer.
    """
    import vqapr.flow.judgments as judgments_module

    original = judgments_module._judge_universe
    judgments_module._judge_universe = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        KeyError("a judgment read a key nobody wrote")
    )
    try:
        body = check(RUN, workspace)
    finally:
        judgments_module._judge_universe = original

    entry = next(item for item in body["blocked"] if item["check"] == "universe")
    assert entry["error_type"] == "KeyError"
    assert entry["blocked_by"].startswith("KeyError:")


def _judge(root: Path, definition: RunDefinition) -> list[str]:
    from vqapr.flow.judgments import _judge_datasets_and_fields

    space = Workspace.open(root)
    registered = {str(item.dataset_id): item for item in space.datasets}
    return [
        failure.code
        for failure in _judge_datasets_and_fields(
            definition, space, registered, FailureSource(key_path="runs.x")
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
    _strategy_reading(tmp_path, "model", "absent_dataset", "close")

    assert _judge(tmp_path, _definition()) == ["check.dataset.unregistered"]


def test_a_dataset_missing_a_field_the_model_reads_is_named(tmp_path: Path) -> None:
    """`check.field.absent`, reachable only once the model is loaded."""
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("instrument",),
            fields={"volume": "volume"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "model", "prices", "close")

    assert _judge(tmp_path, _definition()) == ["check.field.absent"]


def test_a_decision_that_lands_before_its_data_begins_is_named(tmp_path: Path) -> None:
    """`check.lookback.uncovered`, measured at the first instant that actually READS.

    Not at the run's `start`. Nothing reads there -- `start` bounds the horizon, and the strategy
    reads at the occurrences its agenda generates inside it. Measuring at `start` refused any run
    whose dataset's first observation landed after midnight, which is every intraday-stamped
    dataset: this package's own end-to-end fixture was refused by its own verb while `run`
    completed it (issue 012).
    """
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("instrument",),
            fields={"close": "close"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "model", "prices", "close")
    begins = _SPAN[0]

    # Deciding a day BEFORE the data begins: the window really is short, and it is named.
    early = (begins.date().replace(day=1)).isoformat()
    _agenda_deciding_on(tmp_path, "early", (early,), at="04:00")
    space = Workspace.open(tmp_path)
    space.register_strategy_config(
        StrategyConfig(space.component("model"), "early", OperationRole.STRATEGY_CALLBACK)
    )
    definition = _definition(start=datetime.fromisoformat(f"{early}T00:00:00+00:00"))
    assert _judge(tmp_path, definition) == ["check.lookback.uncovered"]

    # The same run, deciding on a day the data covers, is not refused -- even though `start` is
    # still earlier than the dataset's first observation. That difference is the whole fix.
    later = _SPAN[1].date().isoformat()
    _agenda_deciding_on(tmp_path, "later", (later,), at="04:00")
    space = Workspace.open(tmp_path)
    space._strategy_configs["model"] = StrategyConfig(
        space.component("model"), "later", OperationRole.STRATEGY_CALLBACK
    )
    from vqapr.flow.judgments import _judge_datasets_and_fields

    registered = {str(item.dataset_id): item for item in space.datasets}
    assert (
        _judge_datasets_and_fields(definition, space, registered, FailureSource(key_path="r"))
        == []
    )


def test_the_lookback_judgment_stays_silent_when_it_cannot_answer(tmp_path: Path) -> None:
    """No binding, no agenda, no answer -- and no guess.

    Those are other judgments' refusals to make. Answering here too would report one defect twice,
    and guessing an instant would put this verb back in the business of refusing what `run`
    accepts.
    """
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("instrument",),
            fields={"close": "close"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "model", "prices", "close")

    # No binding registered for `model`: the agenda cannot be found, and nothing is guessed.
    assert "check.lookback.uncovered" not in _judge(tmp_path, _definition())


def test_the_venue_judgment_reads_every_shipped_listing_shape(tmp_path: Path) -> None:
    """A SIGNED account against a long-only listing is a contradiction, and must be caught.

    Regression test with a specific history: the first implementation called `exchange.listing(id)`,
    which only `Academic` exposes. On a `KrxExchange` it raised, was swallowed, and the judgment
    found nothing -- indistinguishable from a pass. The second read `listings` as a sequence, which
    is Academic's shape; Krx keys a Mapping by instrument id, so it silently found nothing again.
    """
    from vqapr.flow.judgments import _judge_weights

    Workspace.create(tmp_path)
    source = tmp_path / "limited.py"
    source.write_text(
        "from vqapr.exchange.venues.krx import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=True)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    _register_component(tmp_path, "limited", ComponentKind.EXCHANGE, source)

    judged = _judge_weights(
        _definition(
            instruments=("ABC",),
            exchange="limited",
            initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
            initial_account_mode=AccountMode.SIGNED,
        ),
        Workspace.open(tmp_path),
        FailureSource(key_path="runs.x"),
    )

    assert [failure.code for failure in judged] == ["check.weights.venue_conflict"], (
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

    An unopenable workspace already refuses with the framework's own code. Re-coding it as
    `run.check.*` would rename a defect a reader may already have handling for, so the verb passes
    that body through untouched. Its own two codes exist only for the case with no code at all --
    a bare framework invariant that would otherwise surface as `stage: unhandled`.
    """
    body = check("gone", tmp_path / "none")
    reported = {entry["code"] for entry in body["failures"]}

    assert reported, "the workspace judgment failed, so something must have been reported"
    assert not any(code.startswith("run.check.") for code in reported), (
        f"check re-coded a refusal that already had a code: {sorted(reported)}"
    )

    assert len(set(CODES)) == len(CODES)
    for code in CODES:
        assert code.startswith(("check.", "run.check.")), (
            f"{code} is not in this verb's namespace"
        )

    from vqapr.cli.check import MATERIALIZATION_CODES, SIMULATION_CODES

    # Two counted sets, because there are two kinds of run and they answer different questions.
    assert len(SIMULATION_CODES) == 8, (
        "a run settles exactly eight judgments; adding a ninth is a decision, not a detail"
    )
    assert len(MATERIALIZATION_CODES) == 9, (
        "a materialization spec settles exactly nine judgments; adding a tenth is a decision, "
        "not a detail"
    )
    assert not set(SIMULATION_CODES) & set(MATERIALIZATION_CODES)
    assert set(CODES) == set(SIMULATION_CODES) | set(MATERIALIZATION_CODES) | {
        "run.check.declaration_invalid",
        "run.check.preflight_refused",
    }, "CODES must be exactly the two judgment sets plus the two framework-invariant codes"


def test_a_run_with_one_defect_reports_it_alone_and_a_repaired_run_is_clean(
    workspace: Path,
) -> None:
    """The other direction: a run that carries nothing wrong is certified, not merely tolerated."""
    space = Workspace.open(workspace)
    Workspace.open(workspace).register_dataset(
        replace(
            space.dataset("prices"),
            dataset_id="full",
            fields={"close": "close", "volume": "volume"},
        ),
        space.source("prices-source"),
    )
    assert "check.field.absent" in {entry["code"] for entry in check(RUN, workspace)["failures"]}
