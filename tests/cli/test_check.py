"""`vqapr check` proves a run is ready without starting it, and without writing anything.

Two claims are worth testing and one is worth being careful about.

**Collecting.** `preflight_run` stops at the first refusal, which is right for a gate in front of a
run. `check` was asked a different question -- is this ready -- so it answers about every
independent judgment at once. The test that matters is not that it reports A failure; it is that it
reports the SECOND one too, because a verb that collects and a verb that stops look identical
until there are two things wrong.

**Not mutating.** Asserted byte-for-byte over `.vqapr/`, not claimed in a docstring. The claim
stops precisely at vqapr's own writes: `check` imports user code because `weights` and `records`
are Python, and an imported module can write anywhere. That is stated in the verb's own docstring
rather than papered over, and no test here pretends otherwise.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.cli.check import CODES, check
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

_SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))


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


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace holding one registered dataset and nothing else.

    Deliberately incomplete: a run spec pointed at it will fail several independent judgments,
    which is what makes the collecting behaviour observable.
    """
    space = Workspace.create(tmp_path)
    registration = DatasetRegistration.of(
        "prices",
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    ).with_span(*_SPAN)
    space.register_dataset(registration, SourceSpec.of("prices-source", "prepared/prices"))
    return tmp_path


def test_a_missing_spec_is_reported_rather_than_raised(workspace: Path) -> None:
    """`check` was asked a question; an unreadable spec is the answer, not an exception."""
    body = check(workspace / "nope.yaml", workspace)

    assert body["ok"] is False
    assert body["failures"], "an unreadable spec must produce a reported failure"
    assert body["stage"] == "run.check"


def test_every_check_that_ran_is_named_alongside_every_one_that_could_not(
    workspace: Path,
) -> None:
    """A partial report must not look complete.

    `checked` names the full set, `passed` names what held, and `blocked` names what never ran and
    why. Without the third, a reader cannot tell a judgment that passed from one that was skipped,
    and a spec with an unreadable first phase would look almost clean.
    """
    body = check(workspace / "absent.yaml", workspace)

    assert set(body["checked"]) == {
        "spec",
        "workspace",
        "judgments",
        "declaration",
        "preflight",
    }
    assert "spec" not in body["passed"]
    blocked_names = {entry["check"] for entry in body["blocked"]}
    assert {"declaration", "preflight"} <= blocked_names, (
        "judgments that could not run must be reported as blocked, not silently omitted"
    )
    for entry in body["blocked"]:
        assert entry["blocked_by"], f"{entry['check']} is blocked by nothing, which cannot be"


def test_an_independent_failure_is_not_hidden_by_an_earlier_one(
    tmp_path: Path,
) -> None:
    """The property that separates collecting from stopping.

    The workspace here is absent AND the spec is unreadable. These are independent: neither
    judgment needs the other's result. A verb that stopped at the first would report one failure;
    `check` must report both, because a reader repairing this setup has two things to fix.
    """
    body = check(tmp_path / "missing.yaml", tmp_path / "no-such-project")

    assert body["ok"] is False
    assert len(body["failures"]) >= 2, (
        "two independent judgments failed but only "
        f"{len(body['failures'])} was reported, so check is stopping rather than collecting"
    )


def _spec(root: Path, **overrides: object) -> Path:
    """A run spec with four independent defects, unless a test repairs some of them."""
    import yaml

    document: dict[str, object] = {
        "strategy": {"agenda_id": "absent", "component": "absent"},
        "valuation": {"agenda_id": "absent"},
        "instruments": [],
        "start": "2025-06-01T00:00:00+00:00",
        "end": "2024-01-01T00:00:00+00:00",
        "exchange": "absent",
        "execution_input": "absent",
        "initial_account": {
            "mode": "LONG_ONLY",
            "cash": "1000",
            "positions": {"A005930": "-5"},
        },
    }
    document.update(overrides)
    target = root / "spec.yaml"
    target.write_text(yaml.safe_dump(document), encoding="utf-8")
    return target


def test_four_simultaneous_problems_return_four_failures_in_one_call(
    workspace: Path,
) -> None:
    """AC-C3, and the reason this verb exists.

    An empty universe, a reversed period, a short in a long-only account and an unresolvable
    component are four INDEPENDENT defects: none has to be repaired before another can be judged.
    A verb that stopped at the first would make this four round trips, each one a full workspace
    open and re-read, and the reader would not know how many remained.
    """
    body = check(_spec(workspace), workspace)

    assert body["ok"] is False
    assert len(body["failures"]) >= 4, (
        f"four independent defects produced only {len(body['failures'])} refusal(s): "
        f"{[entry['code'] for entry in body['failures']]}"
    )

    reported = {entry["code"] for entry in body["failures"]}
    assert {
        "check.universe.absent",
        "check.period.uncovered",
        "check.weights.mode_conflict",
    } <= reported, f"a judgment did not report its own defect: {sorted(reported)}"


def test_each_judgment_carries_the_five_fields_a_reader_acts_on(workspace: Path) -> None:
    """AC-C4. A refusal without `fix` is a diagnosis, which is what this envelope replaced."""
    for entry in check(_spec(workspace), workspace)["failures"]:
        for field in ("code", "source", "requirement", "observed", "fix", "explain"):
            assert field in entry, f"{entry['code']} lost {field}"
        assert entry["fix"], f"{entry['code']} says what is wrong but not what to do"
        assert entry["explain"], f"{entry['code']} points at no recovery guidance"
        assert entry["source"]["file"], (
            f"{entry['code']} does not name the spec it refused, so the reader must guess"
        )


def test_repairing_one_defect_leaves_the_others_reported(workspace: Path) -> None:
    """Independence, from the other direction.

    If the judgments were secretly coupled, fixing one would change what the others report. This
    fixes the universe and asserts the period and account refusals survive untouched.
    """
    before = {entry["code"] for entry in check(_spec(workspace), workspace)["failures"]}
    after = {
        entry["code"]
        for entry in check(_spec(workspace, instruments=["A005930"]), workspace)["failures"]
    }

    assert "check.universe.absent" in before
    assert "check.universe.absent" not in after, "the repair was not observed"
    assert {"check.period.uncovered", "check.weights.mode_conflict"} <= after, (
        "repairing one judgment changed what another reported, so they are not independent"
    )


def test_a_boundary_that_cannot_be_compared_is_reported_not_skipped(workspace: Path) -> None:
    """A naive boundary is its own defect and gets its own report.

    This branch was a silent `return []` for one generation: fixing the string-comparison bug lost
    the case the string comparison happened to get right, and nothing failed. A judgment that
    cannot compare must say so -- reporting nothing is indistinguishable from reporting fine.
    """
    from vqapr.cli.check import _judge_period
    from vqapr.domain.errors import FailureSource

    at = FailureSource(file="spec.yaml")
    naive = _judge_period({"start": "2024-01-01T00:00:00", "end": "2024-06-01T00:00:00+00:00"}, at)

    assert [failure.code for failure in naive] == ["check.period.uncovered"]
    assert "start" in (naive[0].observed or "")
    assert "offset" in naive[0].fix, "the fix must name what makes the boundary comparable"

    # And the reversed-but-comparable case still reports, so this did not swallow the other branch.
    reversed_period = _judge_period(
        {"start": "2025-06-01T00:00:00+00:00", "end": "2024-01-01T00:00:00+00:00"}, at
    )
    assert [failure.code for failure in reversed_period] == ["check.period.uncovered"]


def test_a_valid_period_across_two_offsets_is_accepted(workspace: Path) -> None:
    """The bug the comparison fix existed for, pinned so it cannot come back.

    `2024-01-02T00:00:00+09:00` sorts AFTER `2024-01-01T20:00:00+00:00` as a string while being
    five hours earlier as an instant. Compared as text, `check` refused a period `run` accepts --
    a gate contradicting the thing it gates.
    """
    from vqapr.cli.check import _judge_period
    from vqapr.domain.errors import FailureSource

    judged = _judge_period(
        {"start": "2024-01-02T00:00:00+09:00", "end": "2024-01-01T20:00:00+00:00"},
        FailureSource(file="spec.yaml"),
    )

    assert judged == [], "a valid five-hour period was refused, so this is comparing text again"


def test_a_blocked_judgment_names_its_error_type_separately(workspace: Path) -> None:
    """A framework bug and a routine block must not read the same.

    `blocked_by` is one sentence; `error_type` is the field a reader filters on. Without it a
    `KeyError` -- which almost certainly means this verb is wrong -- looks exactly like a
    `VqaprError`, which means the framework declined to answer.
    """
    import vqapr.cli.check as check_module

    original = check_module._judge_universe
    check_module._judge_universe = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        KeyError("a judgment read a key nobody wrote")
    )
    try:
        body = check(_spec(workspace), workspace)
    finally:
        check_module._judge_universe = original

    entry = next(item for item in body["blocked"] if item["check"] == "universe")
    assert entry["error_type"] == "KeyError"
    assert entry["blocked_by"].startswith("KeyError:")


def _strategy_reading(root: Path, dataset_id: str, field: str) -> None:
    """Register a real, loadable strategy that reads one dataset field.

    The shipped scaffold is used rather than a hand-written class because a component that does not
    load is a different refusal, and a fixture that fails to load would make these judgments look
    dead again for a new reason.
    """
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.extension.scaffold import render

    source = root / "model.py"
    source.write_text(
        render(ComponentKind.STRATEGY_MODEL, "model", dataset_id=dataset_id, field=field,
               lookback=3),
        encoding="utf-8",
    )
    object_name = source.read_text(encoding="utf-8").split("class ", 1)[1].split("(", 1)[0]
    Workspace.open(root).register_component(
        ComponentRef.of(
            "model",
            ComponentKind.STRATEGY_MODEL,
            source,
            object_name,
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.STRATEGY_MODEL, object_name=object_name
            ),
        )
    )


def _judge(root: Path, document: dict[str, object]) -> list[str]:
    from vqapr.cli.check import _judge_datasets_and_fields
    from vqapr.domain.errors import FailureSource

    space = Workspace.open(root)
    registered = {str(item.dataset_id): item for item in space.datasets}
    return [
        failure.code
        for failure in _judge_datasets_and_fields(
            document, space, registered, FailureSource(file="spec.yaml")
        )
    ]


def test_the_dataset_judgments_read_the_loaded_model_not_its_reference(workspace: Path) -> None:
    """Three of the eight judgments were permanently dead, and looked implemented.

    `workspace.component()` returns a `ComponentRef` -- an identity, a path and a fingerprint. It
    has no `requirements` attribute at all, so reading it as `getattr(component, "requirements",
    ())` always took the fallback and the loop body never ran: not for any spec, not against any
    workspace. `check.dataset.unregistered`, `check.field.absent` and `check.lookback.uncovered`
    sat in `CODES` looking delivered.

    Only the LOADED model knows what it reads. This pins the distinction, because the failure mode
    is invisible -- a dead judgment reports nothing, which is exactly what a passing judgment
    reports.
    """
    _strategy_reading(workspace, "absent_dataset", "close")

    assert _judge(workspace, {"strategy": {"component": "model"}}) == [
        "check.dataset.unregistered"
    ]


def test_a_dataset_missing_a_field_the_model_reads_is_named(tmp_path: Path) -> None:
    """`check.field.absent`, reachable only once the model is loaded."""
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("instrument",),
            fields={"volume": "volume"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "prices", "close")

    assert _judge(tmp_path, {"strategy": {"component": "model"}}) == ["check.field.absent"]


def test_a_run_starting_before_its_data_begins_is_named(tmp_path: Path) -> None:
    """`check.lookback.uncovered`: the first callbacks would read a short window."""
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("instrument",),
            fields={"close": "close"},
        ).with_span(*_SPAN),
        SourceSpec.of("prices-source", "prepared/prices"),
    )
    _strategy_reading(tmp_path, "prices", "close")

    codes = _judge(
        tmp_path,
        # tz-aware: a naive start names no venue, and `_instant` refuses it rather than
        # comparing it against an aware span and getting a plausible-looking answer.
        {"strategy": {"component": "model"}, "start": "2020-06-01T00:00:00+00:00"},
    )

    assert codes == ["check.lookback.uncovered"]


def test_the_venue_judgment_reads_every_shipped_listing_shape(tmp_path: Path) -> None:
    """A SIGNED account against a long-only listing is a contradiction, and must be caught.

    Regression test with a specific history: the first implementation called `exchange.listing(id)`,
    which only `Academic` exposes. On a `KrxExchange` it raised, was swallowed, and the judgment
    found nothing -- indistinguishable from a pass. The second read `listings` as a sequence, which
    is Academic's shape; Krx keys a Mapping by instrument id, so it silently found nothing again.

    A judgment that cannot fail is not a judgment, so this pins the profile that broke it twice.
    """
    from vqapr.cli.check import _judge_weights
    from vqapr.domain.errors import FailureSource
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component

    space = Workspace.create(tmp_path)
    source = tmp_path / "limited.py"
    source.write_text(
        "from vqapr.exchange.venues.krx import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=True)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    space.register_component(
        ComponentRef.of(
            "limited",
            ComponentKind.EXCHANGE,
            source,
            "Exchange",
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.EXCHANGE, object_name="Exchange"
            ),
        )
    )

    judged = _judge_weights(
        {
            "instruments": ["ABC"],
            "exchange": "limited",
            "initial_account": {"mode": "SIGNED", "cash": "1000", "positions": {}},
        },
        Workspace.open(tmp_path),
        FailureSource(file="spec.yaml"),
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

    check(workspace / "spec.yaml", workspace)

    assert _fingerprint(workspace) == before, "check mutated the workspace"


def test_check_creates_no_workspace_where_none_existed(tmp_path: Path) -> None:
    """Checking an uninitialised directory must not initialise it.

    `Workspace.create` is what several other verbs call on the way in, and calling it here would
    turn a read-only question into the command that made the directory a project.
    """
    check(tmp_path / "spec.yaml", tmp_path)

    assert not (tmp_path / WORKSPACE_DIRECTORY).exists()


def test_this_verb_adds_no_second_name_for_a_defect_that_has_one(tmp_path: Path) -> None:
    """`check` is not a second judge, and the reported codes are the evidence.

    A missing spec and an unopenable workspace both already refuse with the framework's own codes.
    Re-coding them as `run.check.*` would rename defects a reader may already have handling for,
    so the verb passes those bodies through untouched. Its own two codes exist only for the case
    with no code at all -- a bare framework invariant that would otherwise surface as
    `stage: unhandled`.
    """
    body = check(tmp_path / "gone.yaml", tmp_path / "none")
    reported = {entry["code"] for entry in body["failures"]}

    assert reported, "two judgments failed, so something must have been reported"
    assert not any(code.startswith("run.check.") for code in reported), (
        f"check re-coded a refusal that already had a code: {sorted(reported)}"
    )

    assert len(set(CODES)) == len(CODES)
    # Namespaces on purpose. `check.*` are the judgments this verb makes itself; `run.check.*`
    # name a framework invariant that has no code of its own, and exist only so it cannot surface
    # as `stage: unhandled`.
    for code in CODES:
        assert code.startswith(("check.", "run.check.")), (
            f"{code} is not in this verb's namespace"
        )

    from vqapr.cli.check import MATERIALIZATION_CODES, SIMULATION_CODES

    # Two counted sets, because there are two kinds of run and they answer different questions.
    # Counting them together would let a materialization judgment silently take the place of a
    # simulation one.
    assert len(SIMULATION_CODES) == 8, (
        "a simulation spec settles exactly eight judgments; adding a ninth is a decision, not a "
        "detail"
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
    # `check.spec.kind_ambiguous` is deliberately absent: it is an InputError about WHICH spec is
    # being held, not a judgment about a spec that was read.
    assert "check.spec.kind_ambiguous" not in CODES
