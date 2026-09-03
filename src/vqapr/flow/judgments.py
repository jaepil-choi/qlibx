"""The judgments a run must pass, owned by neither verb that asks them.

These answer one question -- is this run worth starting? -- and both `check` and `run` need the
answer. They lived in `cli/check.py` because `check` was built on top of `run`'s spec vocabulary and
so the judgments landed in the verb that needed them first. That left `run` executing what `check`
would refuse: a real look-ahead ran to completion, wrote a permanent record, and appeared beside
legitimate runs with nothing marking it (`docs/issues/015`).

Moving them here is what makes a single answer possible. The module sits below the CLI and imports
nothing from it, so both verbs can reach the same judgments without either importing the other.

**Judged on a `RunDefinition` since record `139`.** A run is a registered declaration rather than
a spec file, so the judgments read the definition the workspace holds -- and each of its strategies
is judged in turn, since one run now names several.

`judgments` returns its blocked list rather than filling a caller-supplied one. The out-parameter
it replaced was easy to forget -- and forgetting it means a run whose judgment could not ANSWER
reports as clean, which is the divergence this module exists to close, reproduced one layer down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from difflib import get_close_matches
from typing import Any

from vqapr.account.account import AccountMode
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError

# Through `extension/`, not `_internal/`, matching `flow/preflight.py:27-28` and
# `flow/materialize.py:30`. Two names for one authority is how a later deletion of the
# adapters misses a caller (`docs/issues/029`).
from vqapr.extension.loading import load_data_model, load_exchange, load_strategy_model
from vqapr.flow.preflight import derived_agenda
from vqapr.flow.run import DataModelEntry, RunDefinition, StrategyEntry

# `vqapr.workspace`, not `vqapr.public`. The facade is the CLI's supported surface and sits ABOVE
# this layer; a module under `flow/` importing it reaches back up through the thing it is supposed
# to sit beneath. `flow/preflight.py` takes the same class from the same place, and the boundary
# tripwire in `docs/design/agent-first-surface.md` counts modules that do otherwise.
from vqapr.workspace import Workspace

__all__ = ["judgments"]


def judgments(
    definition: RunDefinition, workspace: Workspace
) -> tuple[list[Failure], list[dict[str, str]]]:
    """The eight judgments, each answered independently of the others, for every strategy.

    Independence is the whole design: each of the five judges reads the definition and the
    workspace and answers on its own, so a run carrying four defects produces four refusals in a
    single call. Within two of them a later code is gated behind an earlier one -- an absent
    dataset suppresses the field and lookback questions about it, because there is nothing to ask
    them of -- and each such gate carries its own reason.

    A judgment that could not ANSWER is recorded as blocked, carrying the exception type separately
    from its message so a framework bug reads differently from a routine decline. It is never
    reported as passing, and `ok` is false while anything is blocked.
    """
    found: list[Failure] = []
    blocked: list[dict[str, str]] = []
    at = FailureSource(key_path=f"runs.{definition.run_id}")
    registered = {str(item.dataset_id): item for item in workspace.datasets}

    judges = (
        ("universe", lambda: _judge_universe(definition, at)),
        ("period", lambda: _judge_period(definition, at)),
        ("execution_ordering", lambda: _judge_execution_ordering(definition, workspace, at)),
        ("datasets", lambda: _judge_datasets_and_fields(definition, workspace, registered, at)),
        ("weights", lambda: _judge_weights(definition, workspace, at)),
        ("outputs", lambda: _judge_outputs(definition, registered, at)),
    )
    for name, judge in judges:
        try:
            found.extend(judge())
        except Exception as error:
            # One judgment failing to ANSWER must not silence the others -- letting the exception
            # abort the loop would quietly restore the stop-at-first behaviour this verb exists to
            # replace. But swallowing it silently is the worse half of that trade: the judgment
            # did not find nothing, it could not look, and a run nothing was proven about would
            # then report as clean and ready. So it is recorded as BLOCKED. `error_type` rides
            # separately so a reader can tell a `VqaprError` (the framework declining to answer)
            # from a `KeyError` (almost certainly this verb being wrong) at a glance.
            blocked.append(
                {
                    "check": name,
                    "error_type": type(error).__name__,
                    "blocked_by": f"{type(error).__name__}: {error}",
                }
            )
    return found, blocked


def _key(at: FailureSource, *path: str) -> FailureSource:
    return replace(at, key_path=".".join((at.key_path or "", *path)).strip("."))


def _judge_universe(definition: RunDefinition, at: FailureSource) -> list[Failure]:
    """A run with no instruments has nothing to decide about.

    A `RunDefinition` refuses an empty universe at construction, so a registered run cannot reach
    this with none; the judgment stays because `check` promises the eight questions and a reader
    counting them should find each one asked.
    """
    if definition.instruments:
        return []
    return [
        Failure.bounded(
            "check.universe.absent",
            "a run must declare at least one instrument to decide about",
            observed=f"instruments: {definition.instruments!r}",
            fix="list the instrument ids the run trades under `instruments:` in the run",
            explain=ExplainTopic.RUN_PRECONDITION,
            source=_key(at, "instruments"),
        )
    ]


def _instant(value: object) -> datetime | None:
    """One declared timestamp as an aware instant, or `None` when it is not one.

    Comparing these as STRINGS is wrong in both directions, and quietly. `2024-01-02T00:00:00+09:00`
    sorts after `2024-01-01T20:00:00+00:00` while being five hours EARLIER, so a valid period reads
    as reversed and `check` refuses what `run` accepts -- a gate contradicting the thing it gates.
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


def _judge_period(definition: RunDefinition, at: FailureSource) -> list[Failure]:
    """The declared period must be a real interval, not a point or a reversal."""
    start, end = definition.start, definition.end
    if start is None or end is None:
        return [
            Failure.bounded(
                "check.period.uncovered",
                "a run must declare both start and end so its period is bounded",
                observed=f"start={start!r}, end={end!r}",
                fix="declare both start and end as ISO-8601 timestamps with an explicit offset",
                explain=ExplainTopic.RUN_PRECONDITION,
                source=_key(at, "start" if start is None else "end"),
            )
        ]
    if start >= end:
        return [
            Failure.bounded(
                "check.period.uncovered",
                "a run's end must be later than its start",
                observed=f"start={start.isoformat()}, end={end.isoformat()}",
                fix=f"set end later than {start.isoformat()}, or set start earlier than "
                f"{end.isoformat()}",
                explain=ExplainTopic.RUN_PRECONDITION,
                source=_key(at, "end"),
            )
        ]
    return []


def _decide_agenda(workspace: Workspace, definition: RunDefinition) -> object | None:
    """The run's decide agenda, or `None` when it cannot be built here.

    Built from the run's sessions and `at` (record `148`). A dataset that does not resolve
    or a session that does not exist in the zone is a different judgment's refusal to make
    (preflight names it); making it here too would report one defect twice.
    """

    try:
        return derived_agenda(workspace, definition)
    except (VqaprError, ValueError, TypeError):
        return None


def _judge_execution_ordering(
    definition: RunDefinition, workspace: Workspace, at: FailureSource
) -> list[Failure]:
    """AC-C5: a decision cannot fill at an instant that has already passed.

    Caught here, before the run, rather than at the first callback. The old failure mode was a
    bare `ValueError: no exact execution target exists within the run horizon` raised only once
    the simulation was already underway and earlier callbacks had mutated account state.
    """
    if definition.execution_input_id is None:
        return []
    try:
        registration = workspace.execution_input(definition.execution_input_id)
    except VqaprError:
        return []
    fill_at = registration.fill.local_time
    found: list[Failure] = []
    for entry in definition.strategies:
        agenda = _decide_agenda(workspace, definition)
        if agenda is None:
            continue
        late = [
            occurrence.occurrence_id
            for occurrence in agenda.occurrences
            if occurrence.local_instant.local_time >= fill_at
        ]
        if not late:
            continue
        found.append(
            Failure.bounded(
                "check.execution.not_after_decision",
                "every decision must be strictly earlier than the instant it fills at",
                observed=(
                    f"strategy {entry.component_id!r} fills at {fill_at.isoformat()}; "
                    f"{len(late)} occurrence(s) at or after it"
                ),
                examples=late,
                example_total=len(late),
                fix=(
                    f"move the strategy cadence earlier than {fill_at.isoformat()}, or declare a "
                    "fill convention whose instant is later than every decision"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
                source=_key(at, "strategies", entry.component_id),
            )
        )
    return found


def _judge_datasets_and_fields(
    definition: RunDefinition,
    workspace: Workspace,
    registered: dict[str, Any],
    at: FailureSource,
) -> list[Failure]:
    """Every dataset a component reads must be registered, and expose the field it names.

    Two codes rather than one, because they are two different repairs: an unregistered dataset is
    fixed by registering it, and an absent field is fixed by correcting the component or the
    source. Collapsing them would tell the reader which command failed but not which to run.
    """
    found: list[Failure] = []
    members = [
        *(("strategies", entry, load_strategy_model) for entry in definition.strategies),
        *(("datamodels", entry, load_data_model) for entry in definition.datamodels),
    ]
    for section, entry, loader in members:
        source = _key(at, section, entry.component_id)
        try:
            ref = workspace.component(entry.component_id)
            # LOAD the component. `workspace.component()` returns a `ComponentRef` -- an identity,
            # a path and a fingerprint -- which has no `requirements` attribute at all. Only the
            # loaded model knows what it reads.
            component = loader(ref, project_root=workspace.project_root)
        except (VqaprError, TypeError, ValueError):
            # The component does not resolve or does not load. `check.dataset.unregistered` is
            # about a dataset, and the conformance judgments already own that refusal.
            continue

        first_read = _first_decision(definition, workspace, entry)
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
                            else f"register {dataset_id!r} with `vqapr register <declaration>`"
                        ),
                        explain=ExplainTopic.WORKSPACE_STATE,
                        source=source,
                    )
                )
                continue

            exposed = set(registration.fields)
            field_id = str(getattr(requirement, "field_id", ""))
            if field_id and field_id not in exposed:
                found.append(
                    Failure.bounded(
                        "check.field.absent",
                        f"dataset {dataset_id!r} must expose every field the component reads",
                        observed=(f"missing: {field_id}; exposed: {', '.join(sorted(exposed))}"),
                        examples=(field_id,),
                        example_total=1,
                        fix=(
                            f"add {field_id} to the dataset's fields mapping and register it "
                            "again, or read a field it already exposes"
                        ),
                        explain=ExplainTopic.DATASET_PREPARATION,
                        source=source,
                    )
                )

            lookback = getattr(requirement, "lookback", None)
            rows = getattr(lookback, "rows", None)
            span = getattr(registration, "span", None)
            # Measured against the first instant that actually READS, not against the run's
            # `start`. Nothing reads at `start`: it bounds the horizon, and the strategy reads at
            # the occurrences its agenda generates inside that horizon (issue 012).
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
                            f"start the run late enough that its first decision falls at or "
                            f"after {span[0]}, or prepare the dataset with history reaching "
                            "further back"
                        ),
                        explain=ExplainTopic.DATASET_PREPARATION,
                        source=_key(at, "start"),
                    )
                )
    return found


def _judge_outputs(
    definition: RunDefinition, registered: dict[str, Any], at: FailureSource
) -> list[Failure]:
    """A datamodel run writes a dataset that does not exist yet (record `148`).

    The refusal preflight raises at `preflight.datamodel.output_registered`, asked here so
    `check` cannot certify a run that `run` then refuses.
    """
    found: list[Failure] = []
    for entry in definition.datamodels:
        if entry.dataset_id not in registered:
            continue
        found.append(
            Failure.bounded(
                "check.datamodel.output_registered",
                "a datamodel run writes a dataset that does not exist yet",
                observed=f"{entry.dataset_id!r} is already registered",
                fix=(
                    f"declare a new dataset_id for {entry.component_id!r}, or remove the "
                    f"existing {entry.dataset_id} registration from the workspace first"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                source=_key(at, "datamodels", entry.component_id, "dataset_id"),
            )
        )
    return found


def _first_decision(
    definition: RunDefinition, workspace: Workspace, entry: StrategyEntry | DataModelEntry
) -> datetime | None:
    """When one strategy first reads, or `None` when that cannot be answered here.

    The earliest occurrence its agenda generates inside the declared horizon. `None` whenever the
    agenda, the horizon or the ids are missing or unresolvable -- those are other judgments'
    refusals to make, and answering them here would report one defect twice.
    """
    start, end = definition.start, definition.end
    if start is None or end is None:
        return None
    agenda = _decide_agenda(workspace, definition)
    if agenda is None:
        return None
    inside = [
        moment
        for moment in (occurrence.local_instant.instant for occurrence in agenda.occurrences)
        if start <= moment <= end
    ]
    return min(inside) if inside else None


def _judge_weights(
    definition: RunDefinition, workspace: Workspace, at: FailureSource
) -> list[Failure]:
    """The account mode and the venue must both permit the positions the run can take.

    Two codes for two different contradictions: a long-only account that will be asked to short,
    and a venue whose listings do not permit the side the account allows. Both are declared facts
    that disagree, and both are answerable before the run.
    """
    found: list[Failure] = []
    snapshot, mode = definition.initial_account_snapshot, definition.initial_account_mode
    if snapshot is None or mode is None:
        return found

    if mode is AccountMode.LONG_ONLY:
        shorts = [name for name, quantity in snapshot.positions.items() if quantity < 0]
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
                    source=_key(at, "initial_account", "positions"),
                )
            )

    # The venue side of the same contradiction. A SIGNED account claims it may hold a negative
    # position; a listing marked LONG_ONLY or NONE says the venue will not fill one. Both are
    # declared facts, they disagree, and the disagreement is answerable now rather than at the
    # first callback that tries to short.
    if definition.exchange is None or mode is not AccountMode.SIGNED:
        return found
    try:
        exchange = load_exchange(
            workspace.component(definition.exchange), project_root=workspace.project_root
        )
    except (VqaprError, TypeError, ValueError):
        # The exchange does not resolve or does not load; that is another judgment's refusal to
        # make, and making it here too would report one defect twice.
        return found

    # `listings` rather than `listing(id)`: every shipped profile exposes the collection, but only
    # `Academic` exposes the single-id lookup. KrxExchange keys its rules by instrument id;
    # Academic carries a tuple of Listing. Both are shipped profiles, so reading only one shape
    # made this judgment silently find nothing on the other -- which reads exactly like a pass.
    listings = getattr(exchange, "listings", None) or ()
    if isinstance(listings, Mapping):
        declared = {str(name): getattr(rule, "access", None) for name, rule in listings.items()}
    else:
        declared = {
            str(getattr(listing, "instrument_id", "")): getattr(listing, "access", None)
            for listing in listings
        }
    unshortable = [
        f"{name}: {declared[name]}"
        for name in definition.instruments
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
            source=_key(at, "initial_account", "mode"),
        )
    )
    return found
