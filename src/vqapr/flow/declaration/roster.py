"""The preflight half of the instrument declaration gate (design §6.3).

Zero declarations means no order can ever succeed -- the venue must know what each ordered id IS
before it can size or charge it -- so a strategy run over such a project has no reason to start.
Two doors raise the one refusal built here: `preflight_run`, which stops the run, and the
`check` judgment, which reports it beside everything else wrong with the declaration.

The runtime half (`instrument.undeclared`, an order naming an id the roster never described)
lives in `domain/instruments.py`: it needs no workspace, only the roster and the order.
"""

from __future__ import annotations

from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.workspace.registry import Workspace

ROSTER_ABSENT = "roster.absent"
"""Spelled here for preflight and again in `judgments.py` for `check`, the way
`run.output_registered` is: the judgments module publishes its own list from the literals it
spells, and a test holds the two spellings to one string."""


def absent_roster_failure(run_id: str, *, source: FailureSource | None = None) -> Failure:
    """The one refusal for "this project has declared no instrument", worded once for both doors."""
    return Failure.bounded(
        ROSTER_ABSENT,
        (
            "a strategy run needs at least one declared instrument, because the venue must know "
            "what every ordered id IS before it can size or charge it"
        ),
        status=Status.PRECONDITION,
        observed=f"run {run_id!r} is a strategy run and this project has registered no roster",
        fix=(
            "declare the instruments the run may order -- `vqapr new instruments <ids...>` writes "
            "the tables and the declaration; `vqapr register instruments.yaml` registers them"
        ),
        source=source,
    )


def require_declared_roster(workspace: Workspace, *, run_id: str) -> None:
    """Refuse a strategy run before it freezes when the project has declared no instrument.

    Only the POINTER is read here, not the tables: registration refuses an empty table, so a
    pointer that exists is a roster with at least one instrument, and the tables themselves are
    read once, fresh, at run start (`flow/roster.py`). A pointer that exists but is damaged
    raises `roster.unreadable` from `registered_instruments` and is not caught: absent and broken
    stay different states.
    """
    if workspace.registered_instruments() is not None:
        return
    raise VqaprError(
        stage=Stage.FREEZE,
        failures=[absent_roster_failure(run_id)],
        mutation=False,
        retry_precondition="register an instrument roster, then retry",
    )
