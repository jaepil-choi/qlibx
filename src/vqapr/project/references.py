"""What still points at a declaration, and the refusal that names it.

A registration may not be withdrawn while something else names it, so `remove` asks this before it
writes -- and asks it of the state it already holds, inside the lock, so the check and the write
see one snapshot. The docstring below says what asking twice cost.

Free functions for the same reason as `merge.py`: none of the three read `self`. They take the
state to search, which is what makes "check under the lock" expressible at all.
"""

from __future__ import annotations

from collections.abc import Mapping

from vqapr.domain.errors import Stage, Status, VqaprError
from vqapr.project.refusals import _workspace_error
from vqapr.project.run import RunDefinition
from vqapr.project.state import _State


def _references_in(state: _State, kind: str, identity: str) -> tuple[str, ...]:
    """The same question asked of a state already in hand.

    Split out so the check and the write can see ONE snapshot. When this walked its own read,
    `remove` performed two reads with no lock across them and a competing registration could
    land between them -- and because `_decode` validates forward references, the result was a
    workspace `Workspace.open()` refuses rather than merely a stale answer.
    """
    # By name: the tuple lost a member when `execution_inputs` retired (record 185),
    # and a positional read here was the one place that noticed too late.
    components = state.components
    runs: Mapping[str, RunDefinition] = state.runs
    blockers: list[str] = []
    if kind == "component":
        for run_id, definition in runs.items():
            named = {definition.exchange, definition.member.component_id, *definition.compliance}
            if identity in named:
                blockers.append(f"run {run_id!r}")
    elif kind == "dataset":
        # What the DOCUMENT knows names a dataset: a registered datamodel run whose
        # trading days come from it (`agenda.days_from`). A component's reads are declared in
        # its code, not here, so a strategy that reads a withdrawn dataset is refused by
        # `check` and `run` at its next preflight (`check.dataset.unregistered`), which is the
        # same place it would be refused had the dataset never been registered. A datamodel
        # run that WRITES this dataset is not a blocker: withdrawing the output is how that
        # run is run again (`docs/issues/archive/060`).
        for run_id, definition in runs.items():
            if definition.agenda.days_from == identity:
                blockers.append(f"run {run_id!r} (agenda.days_from)")
            # The venue table is a dataset too (record 185): a run that fills against
            # it holds it by name in the document.
            if definition.execution is not None and definition.execution.dataset == identity:
                blockers.append(f"run {run_id!r} (execution)")
    elif kind == "run":
        # A run is the top of the document: nothing names a run, and a run's RECORDS are
        # not registrations -- `vqapr rm run` removes those separately.
        return ()
    else:
        raise _workspace_error(
            stage=Stage.REMOVE,
            code="remove.unsupported_kind",
            status=Status.INVALID,
            requirement="kind must be one this workspace stores",
            observed=repr(kind),
            fix="use one of: dataset, component, run",
            retry="retry with a kind this workspace stores",
        )
    if kind == "component" and identity not in components:
        return ()
    return tuple(sorted(blockers))


def _config_lookup[T](
    key: str,
    declarations: Mapping[str, T],
    label: str,
    *,
    noun: str = "run_id",
) -> T:
    if not isinstance(key, str) or not key:
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="run.invalid",
            status=Status.INVALID,
            requirement=f"{label} lookup requires a valid {noun}",
            observed=repr(key),
            fix=f"pass a non-empty {noun} string to look up this configuration",
            retry=f"use a valid {noun}, then retry",
        )
    try:
        return declarations[key]
    except KeyError as error:
        what = {"component_id": "strategy", "run_id": "run"}.get(noun, "agenda")
        raise _workspace_error(
            stage=Stage.LOOKUP,
            code="run.unregistered",
            status=Status.MISSING,
            requirement=f"{label} for {what} {key!r} must be registered",
            observed=f"registered {label}s: {', '.join(sorted(declarations)) or '(none)'}",
            fix=f"register a {label} for {what} {key!r}, or use one of the ids listed above",
            retry=f"register the {label}, then retry",
            cause=error,
        ) from error


def _reference_error(requirement: str, *, fix: str) -> VqaprError:
    return _workspace_error(
        stage=Stage.REGISTER,
        code="run.reference_invalid",
        status=Status.INVALID,
        requirement=requirement,
        observed="referenced declaration is absent or differs from the registered declaration",
        fix=fix,
        retry="register matching referenced declarations before retrying",
    )
