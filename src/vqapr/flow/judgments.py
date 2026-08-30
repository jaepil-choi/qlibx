"""The judgments a run spec must pass, owned by neither verb that asks them.

These answer one question -- is this spec worth starting? -- and both `check` and `run` need the
answer. They lived in `cli/check.py` because `check` was built on top of `run`'s spec vocabulary and
so the judgments landed in the verb that needed them first. That left `run` executing specs that
`check` would refuse: a real look-ahead ran to completion, wrote a permanent record, and appeared in
`vqapr list runs` beside legitimate runs with nothing marking it (`docs/issues/015`).

Moving them here is what makes a single answer possible. The module sits below the CLI and imports
nothing from it, so both verbs can reach the same judgments without either importing the other.

`_judgments` returns its blocked list rather than filling a caller-supplied one. The out-parameter
it replaced was easy to forget -- and forgetting it means a spec whose judgment could not ANSWER
reports as clean, which is the divergence this module exists to close, reproduced one layer down.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from vqapr._internal.extensions.loading import load_exchange, load_strategy_model
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError
from vqapr.flow.run_spec import MATERIALIZATION
from vqapr.public import Workspace

__all__ = ["judgments", "materialization_judgments"]


def materialization_judgments(
    document: dict[str, Any],
    workspace: Workspace,
    project_root: Path,
    *,
    kind_spelling: Callable[[Any], str],
) -> list[Failure]:
    """What must hold before a materialization is worth starting.

    Every one of these is a refusal `materialize()` would raise later, hoisted to where it costs
    nothing. That is the whole point of the verb: `check` certifying a spec that `run` then
    refuses is the defect this slice opened with, and extending `run` without extending `check`
    would have re-committed it in the task meant to close a door.

    Raised in the `check.materialize.*` namespace, so `tests/cli/test_check.py`'s pinned count of
    the eight `check.*` judgments a simulation settles stays a statement about simulations.
    """
    from vqapr._internal.extensions.component import ComponentKind

    found: list[Failure] = []

    def refuse(code: str, requirement: str, observed: str, fix: str, key: str) -> None:
        found.append(
            Failure.bounded(
                code=f"check.materialize.{code}",
                requirement=requirement,
                observed=observed,
                fix=fix,
                explain=ExplainTopic.DECLARATION_SHAPE,
                source=FailureSource(key_path=key),
            )
        )

    component_id = str(document.get(MATERIALIZATION) or "")
    try:
        ref = workspace.component(component_id)
    except Exception as unknown:
        refuse(
            "component_unregistered",
            "the named component must be registered in this workspace",
            f"{component_id!r}: {unknown}",
            f"register it with `vqapr register datamodel {component_id} <file>.py`",
            MATERIALIZATION,
        )
        ref = None
    if ref is not None and ref.kind is not ComponentKind.DATA_MODEL:
        refuse(
            "component_wrong_kind",
            "a materialization runs a DataModel",
            f"{component_id!r} is registered as {kind_spelling(ref.kind)}",
            f"name a registered datamodel, or declare `strategy: {component_id}` to simulate",
            MATERIALIZATION,
        )

    # The refusal `materialize()` raises at `materialize.input.dataset_exists`, asked here instead.
    # Without this, `check` returns ok:true and `run` refuses -- exactly the shape T1 removed.
    output = document.get("output")
    declared_output = str(output.get("dataset_id", "")) if isinstance(output, dict) else ""
    if declared_output and any(
        str(item.dataset_id) == declared_output for item in workspace.datasets
    ):
        refuse(
            "output_registered",
            "a materialization writes a dataset that does not exist yet",
            f"{declared_output!r} is already registered",
            f"choose a new dataset_id, or remove the existing {declared_output} registration",
            "output.dataset_id",
        )

    declared_instants = document.get("evaluate_at") or ()
    if not declared_instants:
        refuse(
            "no_evaluation_instants",
            "a materialization must say when to evaluate",
            "`evaluate_at:` is empty",
            "list at least one timezone-aware instant under `evaluate_at:`",
            "evaluate_at",
        )
    else:
        # The ninth judgment, added deliberately. `_instant` returns None for anything it cannot
        # read -- including a naive datetime -- and the judgments below simply skipped those, so a
        # spec with a naive `evaluate_at` passed `check` with ok:true and was then refused by
        # `run`. That is the check-certifies-what-run-refuses divergence this slice exists to
        # close, found by the boundary gate inside the task meant to close it.
        unreadable = [
            str(value) for value in declared_instants if _instant(value) is None
        ]
        if unreadable:
            refuse(
                "evaluation_instant_invalid",
                "every `evaluate_at:` entry must be a timezone-aware instant",
                f"cannot read as an instant: {', '.join(unreadable)}",
                (
                    "write each instant with an explicit offset, like "
                    "2024-03-06T04:00:00+09:00; a naive datetime is refused rather than assumed "
                    "to be in any particular zone"
                ),
                "evaluate_at",
            )
    if not (document.get("instruments") or ()):
        refuse(
            "no_instruments",
            "a materialization must say what to evaluate over",
            "`instruments:` is empty",
            "list at least one instrument id under `instruments:`",
            "instruments",
        )

    # What the model says it reads must be registered, or the first evaluation refuses on data the
    # author could have been told about before the run started.
    if ref is not None and ref.kind is ComponentKind.DATA_MODEL:
        from vqapr._internal.extensions.loading import load_data_model

        by_id = {str(item.dataset_id): item for item in workspace.datasets}
        # Scoped to the two calls the refusal describes. Wrapping the judgments below in it too
        # reported a malformed `evaluate_at` entry as `component_unloadable` -- sending the reader
        # to a component that loaded fine -- and let a spec carry `lookback_uncovered` alongside a
        # contradictory `component_unloadable`. `_judgments` avoids the same shape deliberately.
        try:
            requirements = tuple(load_data_model(ref, project_root=project_root).requirements())
        except Exception as unloadable:
            refuse(
                "component_unloadable",
                "the named DataModel must load before its requirements can be judged",
                str(unloadable),
                "fix the component so it loads, then check again",
                MATERIALIZATION,
            )
            requirements = ()
        if requirements:
            absent = sorted(
                {
                    str(requirement.dataset_id)
                    for requirement in requirements
                    if str(requirement.dataset_id) not in by_id
                }
            )
            if absent:
                refuse(
                    "requirement_unregistered",
                    "every dataset the model declares it reads must be registered",
                    f"unregistered: {', '.join(absent)}",
                    "register the missing datasets, then check again",
                    MATERIALIZATION,
                )
            # The judgment that keeps this verb honest. Without it `check` returns ok:true and
            # `materialize` refuses with `materialize.output.empty` after doing the work -- which
            # is `check` certifying what `run` refuses, the defect this slice opened with,
            # re-committed by the task meant to close a door. Measured at the EARLIEST evaluation
            # instant, because that is the window that can be short.
            declared_times = sorted(
                moment
                for moment in (
                    _instant(value) for value in (document.get("evaluate_at") or ())
                )
                if moment is not None
            )
            earliest = declared_times[0] if declared_times else None
            for requirement in requirements:
                registration = by_id.get(str(requirement.dataset_id))
                rows = getattr(getattr(requirement, "lookback", None), "rows", None)
                span = getattr(registration, "span", None) if registration else None
                begins = _instant(span[0]) if span else None
                if not rows or earliest is None or begins is None or begins <= earliest:
                    continue
                refuse(
                    "lookback_uncovered",
                    (
                        f"dataset {requirement.dataset_id!r} must carry history reaching back "
                        "past the earliest evaluation, or that evaluation reads a short window "
                        "and produces nothing"
                    ),
                    (
                        f"dataset begins {span[0]}, earliest evaluation {earliest.isoformat()}, "
                        f"lookback {rows} row(s)"
                    ),
                    (
                        f"evaluate at or after {span[0]}, or prepare the dataset with history "
                        "reaching further back"
                    ),
                    "evaluate_at",
                )
    return found


def judgments(
    document: dict[str, Any], workspace: Workspace, spec: Path
) -> tuple[list[Failure], list[dict[str, str]]]:
    """The eight judgments, each answered independently of the others.

    Independence is the whole design: each of the five reads the spec and the workspace and answers
    on its own, so a declaration carrying four defects produces four refusals in a single call.
    Within two of them a later code is gated behind an earlier one -- an absent dataset suppresses
    the field and lookback questions about it, because there is nothing to ask them of -- and each
    such gate carries its own reason.

    A judgment that could not ANSWER is recorded as blocked, carrying the exception type separately
    from its message so a framework bug reads differently from a routine decline. It is never
    reported as passing, and `ok` is false while anything is blocked.
    """
    found: list[Failure] = []
    blocked: list[dict[str, str]] = []
    at = FailureSource(file=str(spec))
    registered = {str(item.dataset_id): item for item in workspace.datasets}

    judges = (
        ("universe", lambda: _judge_universe(document, at)),
        ("period", lambda: _judge_period(document, at)),
        ("execution_ordering", lambda: _judge_execution_ordering(document, workspace, at)),
        ("datasets", lambda: _judge_datasets_and_fields(document, workspace, registered, at)),
        ("weights", lambda: _judge_weights(document, workspace, at)),
    )
    for name, judge in judges:
        try:
            found.extend(judge())
        except Exception as error:
            # One judgment failing to ANSWER must not silence the others -- letting the exception
            # abort the loop would quietly restore the stop-at-first behaviour this verb exists to
            # replace. But swallowing it silently is the worse half of that trade: the judgment
            # did not find nothing, it could not look, and a spec nothing was proven about would
            # then report as clean and ready.
            #
            # So it is recorded as BLOCKED, which is the third answer this envelope already
            # carries and which exists for exactly this. Every exception type, not a listed few:
            # an unexpected type is the case most likely to mean the judgment is broken, and that
            # is precisely when reporting a pass would be worst.
            #
            # `error_type` rides separately so a reader can tell the two apart at a glance: a
            # `VqaprError` is the framework declining to answer, while a `KeyError` is almost
            # certainly this verb being wrong. Flattening both into one sentence would let a real
            # defect read like routine bookkeeping.
            blocked.append(
                {
                    "check": name,
                    "error_type": type(error).__name__,
                    "blocked_by": f"{type(error).__name__}: {error}",
                }
            )
    return found, blocked


def _judge_universe(document: dict[str, Any], at: FailureSource) -> list[Failure]:
    """A run with no instruments has nothing to decide about."""
    instruments = document.get("instruments")
    if isinstance(instruments, list) and instruments:
        return []
    return [
        Failure.bounded(
            "check.universe.absent",
            "a run must declare at least one instrument to decide about",
            observed=f"instruments: {instruments!r}",
            fix="list the instrument ids the run trades under `instruments:` in the spec",
            explain=ExplainTopic.RUN_PRECONDITION,
            source=replace(at, key_path="instruments"),
        )
    ]


def _instant(value: object) -> datetime | None:
    """One declared timestamp as an aware instant, or `None` when it is not one.

    Comparing these as STRINGS is wrong in both directions, and quietly. `2024-01-02T00:00:00+09:00`
    sorts after `2024-01-01T20:00:00+00:00` while being five hours EARLIER, so a valid period reads
    as reversed and `check` refuses what `run` accepts -- a gate contradicting the thing it gates.
    The other direction is worse: `str(datetime)` uses a space separator where a quoted spec keeps
    the `T`, and a space sorts below `T`, so a real shortfall compares as fine and is never
    reported. Which of the two happens depends on whether the author quoted the YAML scalar, since
    PyYAML resolves an unquoted ISO-8601 scalar to a `datetime` and a quoted one to `str`.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _judge_period(document: dict[str, Any], at: FailureSource) -> list[Failure]:
    """The declared period must be a real interval, not a point or a reversal."""
    start, end = document.get("start"), document.get("end")
    if start is None or end is None:
        return [
            Failure.bounded(
                "check.period.uncovered",
                "a run must declare both start and end so its period is bounded",
                observed=f"start={start!r}, end={end!r}",
                fix="declare both start and end as ISO-8601 timestamps with an explicit offset",
                explain=ExplainTopic.RUN_PRECONDITION,
                source=replace(at, key_path="start" if start is None else "end"),
            )
        ]
    first, last = _instant(start), _instant(end)
    if first is None or last is None:
        # An uncomparable boundary is its own defect and gets its own report. Returning nothing
        # here was a real regression: the string comparison this replaced happened to get a
        # naive-AND-reversed period right, and silence would have lost that case entirely --
        # against a verb whose whole purpose is reporting every defect in one pass.
        uncomparable = "start" if first is None else "end"
        return [
            Failure.bounded(
                "check.period.uncovered",
                "start and end must be timezone-aware instants so the period can be compared",
                observed=f"{uncomparable}={document.get(uncomparable)!r}",
                fix=(
                    f"write {uncomparable} as an ISO-8601 timestamp with an explicit offset, "
                    "for example 2024-01-01T00:00:00+09:00"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
                source=replace(at, key_path=uncomparable),
            )
        ]
    if first >= last:
        return [
            Failure.bounded(
                "check.period.uncovered",
                "a run's end must be later than its start",
                observed=f"start={first.isoformat()}, end={last.isoformat()}",
                fix=f"set end later than {first.isoformat()}, or set start earlier than "
                f"{last.isoformat()}",
                explain=ExplainTopic.RUN_PRECONDITION,
                source=replace(at, key_path="end"),
            )
        ]
    return []


def _judge_execution_ordering(
    document: dict[str, Any], workspace: Workspace, at: FailureSource
) -> list[Failure]:
    """AC-C5: a decision cannot fill at an instant that has already passed.

    Caught here, before the run, rather than at the first callback. The old failure mode was a
    bare `ValueError: no exact execution target exists within the run horizon` raised only once
    the simulation was already underway and earlier callbacks had mutated account state.
    """
    strategy = document.get("strategy")
    execution_input = document.get("execution_input")
    if not isinstance(strategy, dict) or execution_input is None:
        return []

    agenda_id = strategy.get("agenda_id")
    if agenda_id is None:
        return []
    try:
        agenda = workspace.agenda(str(agenda_id))
        registration = workspace.execution_input(str(execution_input))
    except VqaprError:
        # The id does not resolve; that is a different judgment's refusal to make, and making it
        # here too would report one defect twice.
        return []

    fill_at = registration.fill.local_time
    late = [
        occurrence.occurrence_id
        for occurrence in agenda.occurrences
        if occurrence.local_instant.local_time >= fill_at
    ]
    if not late:
        return []
    return [
        Failure.bounded(
            "check.execution.not_after_decision",
            "every decision must be strictly earlier than the instant it fills at",
            observed=(
                f"fill at {fill_at.isoformat()}; {len(late)} occurrence(s) at or after it"
            ),
            examples=late,
            example_total=len(late),
            fix=(
                f"move the strategy cadence earlier than {fill_at.isoformat()}, or declare a "
                "fill convention whose instant is later than every decision"
            ),
            explain=ExplainTopic.RUN_PRECONDITION,
            source=replace(at, key_path="strategy.agenda_id"),
        )
    ]


def _judge_datasets_and_fields(
    document: dict[str, Any],
    workspace: Workspace,
    registered: dict[str, Any],
    at: FailureSource,
) -> list[Failure]:
    """Every dataset a component reads must be registered, and expose the fields it names.

    Two codes rather than one, because they are two different repairs: an unregistered dataset is
    fixed by registering it, and an absent field is fixed by correcting the component or the
    source. Collapsing them would tell the reader which command failed but not which to run.
    """
    found: list[Failure] = []
    strategy = document.get("strategy")
    if not isinstance(strategy, dict):
        return found

    component_id = strategy.get("component") or strategy.get("component_id")
    if component_id is None:
        return found
    try:
        ref = workspace.component(str(component_id))
        # LOAD the component. `workspace.component()` returns a `ComponentRef` -- an identity, a
        # path and a fingerprint -- which has no `requirements` attribute at all. Reading it with
        # a `getattr(..., ())` fallback made three of this verb's eight judgments permanently
        # unreachable: the loop body never ran, for any spec, against any workspace, and the codes
        # sat in `CODES` looking implemented. Only the loaded model knows what it reads.
        component = load_strategy_model(ref, project_root=workspace.project_root)
    except (VqaprError, TypeError, ValueError):
        # The component does not resolve or does not load. `check.dataset.unregistered` is about a
        # dataset, not about a component that will not import, and the conformance judgments
        # already own that refusal -- reporting it here too would name one defect twice.
        return found

    for requirement in component.requirements() or ():
        dataset_id = str(getattr(requirement, "dataset_id", ""))
        if not dataset_id:
            continue
        registration = registered.get(dataset_id)
        if registration is None:
            close = get_close_matches(dataset_id, sorted(registered), n=1)
            found.append(
                Failure.bounded(
                    "check.dataset.unregistered",
                    f"dataset {dataset_id!r} must be registered before a run can read it",
                    observed=f"registered: {', '.join(sorted(registered)) or '(none)'}",
                    fix=(
                        f"register {dataset_id!r}, or point the component at {close[0]!r}"
                        if close
                        else f"register {dataset_id!r} with `vqapr register <declaration.yaml>`"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    source=replace(at, key_path="strategy.component"),
                )
            )
            continue

        exposed = set(registration.fields)
        missing = [name for name in getattr(requirement, "fields", ()) if name not in exposed]
        if missing:
            found.append(
                Failure.bounded(
                    "check.field.absent",
                    f"dataset {dataset_id!r} must expose every field the component reads",
                    observed=(
                        f"missing: {', '.join(missing)}; "
                        f"exposed: {', '.join(sorted(exposed))}"
                    ),
                    examples=missing,
                    example_total=len(missing),
                    fix=(
                        f"add {', '.join(missing)} to the dataset's fields mapping and register "
                        "it again, or read a field it already exposes"
                    ),
                    explain=ExplainTopic.DATASET_PREPARATION,
                    source=replace(at, key_path="strategy.component"),
                )
            )

        lookback = getattr(requirement, "lookback", None)
        rows = getattr(lookback, "rows", None)
        span = getattr(registration, "span", None)
        # Measured against the first instant that actually READS, not against the run's `start`.
        #
        # Nothing reads at `start`: it bounds the horizon, and the strategy reads at the
        # occurrences its agenda generates inside that horizon. Comparing against it refused specs
        # that run correctly whenever a dataset's first observation lands after midnight -- which
        # is every intraday-stamped dataset, so the fixture this package ships was itself refused
        # by its own verb while `run` completed it (issue 012).
        #
        # Worse than a false positive on its own: `check` exists to prove a spec before a run is
        # spent, so a reader who trusts it stops and starts editing something that already worked.
        # The mirror of `068`, and the same Principle 5.
        first_read = _first_decision(document, workspace)
        begins = _instant(span[0]) if span is not None else None
        if rows and begins is not None and first_read is not None and begins > first_read:
            found.append(
                    Failure.bounded(
                        "check.lookback.uncovered",
                        (
                            f"dataset {dataset_id!r} must carry history reaching back past the "
                            "first decision, or that decision reads a short window"
                        ),
                        observed=(
                            f"dataset begins {span[0]}, first decision "
                            f"{first_read.isoformat()}, lookback {rows} row(s)"
                        ),
                        fix=(
                            f"start the run late enough that its first decision falls at or after "
                            f"{span[0]}, or prepare the dataset with history reaching further back"
                        ),
                        explain=ExplainTopic.DATASET_PREPARATION,
                        source=replace(at, key_path="start"),
                    )
                )
    return found


def _first_decision(document: dict[str, Any], workspace: Workspace) -> datetime | None:
    """When the strategy first reads, or `None` when that cannot be answered here.

    The earliest occurrence its agenda generates inside the declared horizon. `None` whenever the
    agenda, the horizon or the ids are missing or unresolvable -- those are other judgments'
    refusals to make, and answering them here would report one defect twice.
    """
    strategy = document.get("strategy")
    if not isinstance(strategy, dict):
        return None
    agenda_id = strategy.get("agenda_id")
    start, end = _instant(document.get("start")), _instant(document.get("end"))
    if agenda_id is None or start is None or end is None:
        return None
    try:
        agenda = workspace.agenda(str(agenda_id))
    except VqaprError:
        return None
    inside = [
        moment
        for moment in (
            occurrence.local_instant.instant for occurrence in agenda.occurrences
        )
        if start <= moment <= end
    ]
    return min(inside) if inside else None


def _judge_weights(
    document: dict[str, Any], workspace: Workspace, at: FailureSource
) -> list[Failure]:
    """The account mode and the venue must both permit the positions the run can take.

    Two codes for two different contradictions: a long-only account that will be asked to short,
    and a venue whose listings do not permit the side the account allows. Both are declared facts
    that disagree, and both are answerable before the run.
    """
    found: list[Failure] = []
    account = document.get("initial_account")
    if not isinstance(account, dict):
        return found

    mode = str(account.get("mode", "")).upper()
    positions = account.get("positions") or {}
    if mode == "LONG_ONLY" and isinstance(positions, dict):
        shorts = [name for name, quantity in positions.items() if str(quantity).startswith("-")]
        if shorts:
            found.append(
                Failure.bounded(
                    "check.weights.mode_conflict",
                    "a long-only account must not open with a short position",
                    observed=f"short: {', '.join(shorts)}",
                    examples=shorts,
                    example_total=len(shorts),
                    fix=(
                        f"drop {', '.join(shorts)} from the initial account, or declare the "
                        "account mode as SIGNED"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                    source=replace(at, key_path="initial_account.positions"),
                )
            )

    # The venue side of the same contradiction. A SIGNED account claims it may hold a negative
    # position; a listing marked LONG_ONLY or NONE says the venue will not fill one. Both are
    # declared facts, they disagree, and the disagreement is answerable now rather than at the
    # first callback that tries to short.
    exchange_id = document.get("exchange")
    instruments = document.get("instruments")
    if exchange_id is None or mode != "SIGNED" or not isinstance(instruments, list):
        return found
    try:
        exchange = load_exchange(
            workspace.component(str(exchange_id)), project_root=workspace.project_root
        )
    except (VqaprError, TypeError, ValueError):
        # The exchange does not resolve or does not load; that is another judgment's refusal to
        # make, and making it here too would report one defect twice.
        return found

    # `listings` rather than `listing(id)`: every shipped profile exposes the collection, but only
    # `Academic` exposes the single-id lookup. Reaching for the method that happens to exist on
    # one profile made this judgment a silent no-op on the others -- it found nothing and reported
    # nothing, which reads exactly like a pass.
    listings = getattr(exchange, "listings", None) or ()
    if isinstance(listings, Mapping):
        # KrxExchange keys its rules by instrument id; Academic carries a tuple of Listing. Both
        # are shipped profiles, so reading only one shape made this judgment silently find nothing
        # on the other -- which reads exactly like a pass.
        declared = {str(name): getattr(rule, "access", None) for name, rule in listings.items()}
    else:
        declared = {
            str(getattr(listing, "instrument_id", "")): getattr(listing, "access", None)
            for listing in listings
        }
    unshortable = [
        f"{name}: {declared[name]}"
        for name in (str(item) for item in instruments)
        # An instrument with no listing at all is `preflight.universe.unlisted_instrument`'s
        # refusal to make; reporting it here too would give one defect two names.
        if name in declared and str(declared[name]) != "signed"
    ]
    if not unshortable:
        return found

    found.append(
        Failure.bounded(
            "check.weights.venue_conflict",
            (
                "a signed account must trade on listings the venue permits a short on, or it "
                "declares a freedom the venue will not fill"
            ),
            observed=f"{len(unshortable)} listing(s) not signed: {', '.join(unshortable[:5])}",
            examples=unshortable,
            example_total=len(unshortable),
            fix=(
                "declare the account mode as LONG_ONLY, or list those instruments with signed "
                "access on the exchange"
            ),
            explain=ExplainTopic.RUN_PRECONDITION,
            source=replace(at, key_path="initial_account.mode"),
        )
    )
    return found


