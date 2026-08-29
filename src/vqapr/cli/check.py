"""`vqapr check <spec.yaml>` — prove a run is ready without starting it or touching anything.

Two properties make this verb worth having, and both are about what it does NOT do.

**It collects.** `preflight_run` raises on the first thing it finds, which is right for a
gate standing in front of a run: the first refusal is the reason the run must not start, and
proving the rest costs time the caller did not ask for. But it makes preparing a declaration a
sequence of round trips -- fix the dataset, re-run, learn the agenda is missing, re-run, learn the
account holds an unlisted name. Each round trip is a full workspace open and a full re-read.
`check` runs the same judgments and reports every INDEPENDENT one together, so an agent repairing
its own setup receives the whole list.

**It does not mutate.** No file under `.vqapr/` is created, moved or rewritten. That is asserted
byte-for-byte in the tests rather than claimed here, and the claim stops exactly there: `check`
imports user code, because `weights` and `records` are Python and there is no way to judge a
component without loading it. `loading.py` executes a user module through
`spec_from_file_location`, so arbitrary user code can write anywhere it likes. This verb does not
sandbox that and does not pretend to; what it guarantees is that *vqapr* writes nothing.

**Dependent checks are reported, not silently dropped.** Some judgments cannot run until an
earlier one passes -- there is no point resolving execution targets for a strategy whose component
will not import. Those are reported as `blocked`, naming what blocked them, so the reader can tell
"this passed" from "this never ran" from "this failed". Reporting them as passed would be a lie,
and omitting them would make a partial report look complete.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from vqapr._internal.extensions.loading import load_exchange, load_strategy_model
from vqapr.cli.envelope import success
from vqapr.cli.inputs import InputError, read_yaml_mapping
from vqapr.cli.run import (
    MATERIALIZATION,
    definition_from_document,
    require_declared_keys,
    spec_kind,
)
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError
from vqapr.public import Workspace, preflight_run

STAGE = "run.check"

SIMULATION_CODES = (
    "check.execution.not_after_decision",
    "check.period.uncovered",
    "check.lookback.uncovered",
    "check.dataset.unregistered",
    "check.field.absent",
    "check.weights.mode_conflict",
    "check.weights.venue_conflict",
    "check.universe.absent",
)
"""The eight judgments this verb makes about a SIMULATION spec.

Each is a question a run must answer YES to before it starts, and each is asked independently of
the others so a declaration with four defects reports four refusals rather than the first one four
times.

Eight, and adding a ninth is a decision rather than a detail. That is why the materialization
judgments below are a separate tuple instead of an extension of this one: they are not more
questions about a simulation, they are the questions a different kind of run has to answer.
"""

MATERIALIZATION_CODES = (
    "check.materialize.component_unregistered",
    "check.materialize.component_wrong_kind",
    "check.materialize.component_unloadable",
    "check.materialize.output_registered",
    "check.materialize.no_evaluation_instants",
    "check.materialize.no_instruments",
    "check.materialize.requirement_unregistered",
    "check.materialize.lookback_uncovered",
    "check.materialize.evaluation_instant_invalid",
)
"""The judgments this verb makes about a MATERIALIZATION spec.

Every one is a refusal `materialize()` raises later, hoisted to where it costs nothing. A verb that
certifies a spec the next command rejects is worse than no verb, because it teaches the reader to
stop trusting it -- `docs/issues/012` records that divergence still open on the simulation side,
and extending `run` without extending `check` would have opened a second one in the task meant to
close a door.

Separately namespaced so the eight above stay a statement about simulations. A reader counting the
judgments a simulation settles gets eight whether or not this tuple ever grows.
"""

CODES = (
    *SIMULATION_CODES,
    *MATERIALIZATION_CODES,
    f"{STAGE}.declaration_invalid",
    f"{STAGE}.preflight_refused",
)
"""Everything this verb can emit: both judgment sets, plus two framework-invariant codes.

The two `run.check.*` codes are different in kind from either set: they name a bare
`TypeError`/`ValueError` from a framework invariant, which has no structured body of its own and
would otherwise surface as `stage: unhandled` -- telling an agent the framework broke when its spec
was wrong. Refusals that DO have a code keep it; `check` is not a second name for a defect that
already has one.
"""


@dataclass(frozen=True, slots=True)
class _Phase:
    """One independently-runnable judgment, and what it needs before it can run."""

    name: str
    needs: tuple[str, ...] = ()


_PHASES = (
    _Phase("spec"),
    _Phase("workspace"),
    _Phase("judgments", needs=("spec", "workspace")),
    _Phase("declaration", needs=("spec", "workspace")),
    _Phase("preflight", needs=("declaration",)),
)
"""The order judgments become answerable in, and nothing more.

`declaration` cannot be built without both a spec to read and a workspace to resolve ids against;
`preflight` cannot freeze a definition that was never built. Everything else runs regardless of
what else failed, which is what makes collecting possible at all.
"""

_MATERIALIZATION_PHASES = (
    _Phase("spec"),
    _Phase("workspace"),
    _Phase("judgments", needs=("spec", "workspace")),
)
"""The same order, minus the two phases that are `RunDefinition`-shaped.

`declaration` builds a `RunDefinition` and `preflight` freezes one, and a materialization has
neither -- no venue, no execution table, no account, no trading period. Running them anyway is not
a near miss: `_judge_period` returns `check.period.uncovered` for any spec without `start`/`end`,
and `ok` is `not failures and not blocked`, so `check` would refuse every valid materialization
spec ever written. That is the mirror of the defect this slice opened with -- a verb refusing what
`run` would accept -- and it is the reason the fork is here rather than at the readers.
"""


def phases_for(document: dict[str, Any] | None) -> tuple[_Phase, ...]:
    """Which phases answer questions about this spec.

    Falls back to the simulation tuple when the document could not be read at all, so a spec that
    fails at the `spec` phase still reports the phases it was measured against.
    """
    if document is None:
        return _PHASES
    try:
        return _MATERIALIZATION_PHASES if spec_kind(document) == MATERIALIZATION else _PHASES
    except InputError:
        # Which kind it is, is itself the refusal. The `spec` phase reports it; this only has to
        # pick a tuple to name in `checked`.
        return _PHASES





def check(spec: Path, project_root: Path) -> dict[str, Any]:
    """Run every answerable judgment and report all of them together.

    Returns the envelope body rather than raising, because a refusal here is the ANSWER to the
    question asked. `run` raises on the same conditions; `check` was asked whether they hold.
    """
    # Rendered bodies rather than `Failure` objects, because two of the three sources already have
    # one: a `VqaprError` carries structured failures and an `InputError` carries its own body.
    # Round-tripping those back through `Failure.bounded` would rebuild what already exists and
    # hand the refusal-code inventory codes it cannot fold.
    failures: list[dict[str, Any]] = []
    passed: list[str] = []
    blocked: list[dict[str, str]] = []
    done: set[str] = set()

    document: dict[str, Any] | None = None
    workspace: Workspace | None = None
    definition: object | None = None

    # Read before the loop, because which phases apply depends on what the spec declares and the
    # loop cannot be iterating a tuple it has not chosen yet. Failures are left to the `spec`
    # phase below, which re-reads and reports them properly -- this only picks the tuple.
    try:
        document = read_yaml_mapping(spec, what="a run spec")
    except Exception:
        document = None
    phases = phases_for(document)
    document = None

    for phase in phases:
        unmet = [need for need in phase.needs if need not in done]
        if unmet:
            blocked.append({"check": phase.name, "blocked_by": ", ".join(unmet)})
            continue

        blocked_before = len(blocked)
        try:
            if phase.name == "spec":
                document = read_yaml_mapping(spec, what="a run spec")
                require_declared_keys(document)
            elif phase.name == "workspace":
                workspace = Workspace.open(project_root)
            elif phase.name == "judgments":
                assert document is not None and workspace is not None
                if phases is _MATERIALIZATION_PHASES:
                    judged = _materialization_judgments(document, workspace, project_root)
                    failures.extend(_render(failure, spec) for failure in judged)
                    if judged:
                        continue
                    done.add(phase.name)
                    passed.append(phase.name)
                    continue
                # The only phase that collects rather than raises. Each judgment is independent,
                # so a spec with four defects must report four refusals -- reporting the first
                # would make the reader fix one thing per round trip, which is the friction this
                # verb exists to remove.
                judged = _judgments(document, workspace, spec, blocked)
                failures.extend(_render(failure, spec) for failure in judged)
                if judged:
                    continue
            elif phase.name == "declaration":
                assert document is not None and workspace is not None
                definition = definition_from_document(document, workspace)
            elif phase.name == "preflight":
                preflight_run(project_root, definition)
        except VqaprError as error:
            # The framework already judged this and said why, in codes a reader may already have
            # handling for. Re-wrapping would replace an actionable refusal with a vaguer one --
            # but the framework was handed ids, not a file, so it cannot know WHICH spec named
            # them. `check` does, and adds only that.
            failures.extend(_render(failure, spec) for failure in error.failures)
            continue
        except InputError as error:
            failures.append(_from_input(error, spec))
            continue
        except Exception as error:
            # Every exception type, not a listed few. A `KeyError` from a spec missing a key, an
            # `AttributeError` from a shape nobody expected -- these are the cases most likely to
            # mean a phase is broken, and letting them escape renders the whole envelope as
            # `stage: "unhandled"`: the framework broke, when the truth is the spec was wrong.
            # `check` was asked a question, and every answer it can give belongs in its envelope.
            failures.append(_render(_from_python(phase.name, error, spec), spec))
            continue

        done.add(phase.name)
        if phase.name == "judgments" and len(blocked) > blocked_before:
            # A judgment that could not look did not pass. The phase is still `done`, because the
            # phases depending on it can still be answered, but claiming it PASSED would report a
            # spec nothing was proven about as clean and ready.
            continue
        passed.append(phase.name)

    return {
        # A blocked judgment is not a failure, but it is not a clean bill either: nothing was
        # proven where it could not look. `ok` says the spec is ready to run, and a spec with an
        # unanswered judgment is not something this verb can vouch for.
        "ok": not failures and not blocked,
        "stage": STAGE,
        "checked": [phase.name for phase in phases],
        "passed": passed,
        "blocked": blocked,
        "failures": failures,
    }


def _materialization_judgments(
    document: dict[str, Any], workspace: Workspace, project_root: Path
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
            f"{component_id!r} is registered as {ref.kind.value}",
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


def _judgments(
    document: dict[str, Any], workspace: Workspace, spec: Path, blocked: list[dict[str, str]]
) -> list[Failure]:
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
    return found


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
        starts = _instant(document.get("start"))
        begins = _instant(span[0]) if span is not None else None
        if rows and begins is not None and starts is not None and begins > starts:
            found.append(
                    Failure.bounded(
                        "check.lookback.uncovered",
                        (
                            f"dataset {dataset_id!r} must carry history reaching back past the "
                            "run start, or the first callbacks read a short window"
                        ),
                        observed=(
                            f"dataset begins {span[0]}, run starts {document['start']}, "
                            f"lookback {rows} row(s)"
                        ),
                        fix=(
                            f"start the run at or after {span[0]}, or prepare the dataset with "
                            "history reaching further back"
                        ),
                        explain=ExplainTopic.DATASET_PREPARATION,
                        source=replace(at, key_path="start"),
                    )
                )
    return found


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


def _render(failure: Failure, spec: Path) -> dict[str, Any]:
    """One refusal in the envelope's own shape, matching `VqaprError.as_dict` field for field.

    A framework refusal knows the id it could not resolve but not the document that named it --
    it was handed a string. Every refusal this verb reports came from ONE spec, so the file is
    supplied here when the refusal has none of its own. Anything the refusal did know is left
    exactly as it was.
    """
    source = failure.source
    if source.file is None:
        source = replace(source, file=str(spec))
    return {
        "code": failure.code,
        "source": source.as_dict(),
        "requirement": failure.requirement,
        "observed": failure.observed,
        "fix": failure.fix,
        "explain": str(failure.explain),
        "examples": list(failure.examples),
        "example_total": failure.example_total,
    }


def _from_input(error: InputError, spec: Path) -> dict[str, Any]:
    """An input refusal's own body, kept whole and told which file it came from.

    Not rebuilt into a `Failure`. Re-coding it as `run.check.*` would rename a defect the reader
    may already have handling for, and reconstructing it through `Failure.bounded` would hand the
    refusal-code inventory a code it cannot fold statically -- so the code would silently drop out
    of the published inventory. Passing the body through costs neither.
    """
    # `error.fix` is the field the envelope publishes; reading `error.retry` instead was a second
    # definition of the same value, which is the very drift this batch fixed elsewhere. And a
    # source the error already carried is kept rather than overwritten -- the error knows its own
    # key path, and this only knows the file.
    # `error.source` directly: `InputError.__init__` always assigns it, and
    # getattr-with-default on a known type is the exact idiom that left three judgments
    # permanently dead one generation ago.
    carried = error.source
    # MERGED, not replaced. The previous form swapped the whole source out whenever `file` was
    # absent -- which is exactly the case where the error carries a `key_path` and no file, so the
    # one field this function cannot know was the one it discarded. That contradicted the comment
    # above it, and it is why a refusal naming `strategy.component` still reported
    # `key_path: null`.
    source = FailureSource(
        file=carried.file or str(spec),
        key_path=carried.key_path,
        line=carried.line,
    )
    return {
        "code": error.code,
        "source": source.as_dict(),
        "requirement": error.requirement,
        "observed": error.observed,
        "fix": error.fix,
        "explain": str(ExplainTopic.DECLARATION_SHAPE),
        "examples": list(error.examples),
        "example_total": error.example_total,
    }


def _from_python(phase: str, error: Exception, spec: Path) -> Failure:
    """A bare TypeError or ValueError from a framework invariant, given an envelope.

    These are the framework's own assertions about a definition's shape. They are real refusals
    with no structured body of their own, so rather than let them surface as `stage: unhandled` --
    which tells an agent the framework broke when its declaration was wrong -- they are named
    here.

    The two codes are written literally rather than selected into a variable so the refusal-code
    inventory's constant folding can see them. A code that reaches the inventory only at runtime
    is a code that drops out of it the first time no fixture happens to trigger this path.
    """
    detail = f"{type(error).__name__}: {error}"
    fix = f"correct the run spec at {spec} so the {phase} phase completes, then check again"
    source = FailureSource(file=str(spec))
    if phase == "declaration":
        return Failure.bounded(
            "run.check.declaration_invalid",
            "the spec must resolve against what the workspace has registered",
            observed=detail,
            fix=fix,
            explain=ExplainTopic.DECLARATION_SHAPE,
            source=source,
        )
    return Failure.bounded(
        "run.check.preflight_refused",
        "every run precondition must hold before the run starts",
        observed=detail,
        fix=fix,
        explain=ExplainTopic.RUN_PRECONDITION,
        source=source,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "spec",
        type=Path,
        help="path to the run spec YAML to check (the same file `vqapr run` takes)",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    body = check(Path(args.spec), project_root)
    if body["ok"]:
        return success(
            STAGE,
            checked=body["checked"],
            passed=body["passed"],
            blocked=body["blocked"],
        )
    return body
