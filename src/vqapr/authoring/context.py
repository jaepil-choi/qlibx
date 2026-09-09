"""The `call` a Model receives, and the typed observations it reads through it.

**One call surface for every Model role.** A DataModel, a StrategyModel and a Constraint declare
their reads the same way -- `inputs()`, keyed by an alias the author names -- and read them the
same way: `call.read(alias, field)` for a panel-grain alias, `call.rows(alias)` for a rows-grain
one. What a StrategyModel additionally receives is what its role needs: the committed account, its
own declared history, the bounds every registered Constraint projected. The difference between
the roles is that list and nothing else (`docs/issues/archive/036`).

**One alias is one scan.** An alias over several fields is several `DataRequirement`s
(`docs/issues/archive/049`: a requirement names one field), and `ModelWindow.declared` reads them in one
statement -- the store's window SQL ranks each field's own last N rows, so the rows come back
already joined on `(instant, instrument)` (record `136`).

**Every read goes through `ModelWindow`.** Nothing here holds a store handle. The window is
bounded to `available_at <= evaluation_time`, carries the consumer id the framework stamped, and
records an `AccessRecord` per read -- what lets the Flow state an intent's provenance and stamp a
datamodel row's `available_at`.

This module is the former `models/` package (`calls.py` + `contexts.py`) as one file; the
`Component` classes themselves live in `vqapr.authoring`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from vqapr.authoring import (
    ConstraintBounds,
    ConstraintCall,
    DataCall,
    DatasetInput,
    EconomicAccountView,
    Observation,
    StrategyCall,
    requirements_for,
)
from vqapr.authoring.history import AccountHistory
from vqapr.data.panel import PanelWindow
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.shapes import Grain


def observations(
    rows: Sequence[Mapping[str, object]],
    *,
    instrument_field: str,
    available_at_field: str,
    fields: Sequence[str],
) -> tuple[Observation, ...]:
    """Project engine rows onto typed observations, carrying only declared fields.

    A row missing its instrument or availability stamp is a schema error rather than a row
    to skip: dropping it silently would turn a broken declaration into a thin result.

    The observations are built through `Observation._framework_row`, without per-row validation.
    `fields` are the alias's declared names, checked once when the `DatasetInput` was declared;
    the scan already returned `available_at` from a `TIMESTAMPTZ` column and the instrument as
    text. `docs/issues/archive/054` measured the validated constructor at 70% of a `rows` read -- 14.6M
    whitespace checks for 159k rows -- re-proving per row what registration proved once.
    """
    declared = tuple(fields)
    build = Observation._framework_row
    observations: list[Observation] = []
    for row in rows:
        if instrument_field not in row:
            raise KeyError(
                f"row is missing the instrument field {instrument_field!r}; "
                "the dataset declaration does not match the physical table"
            )
        if available_at_field not in row:
            raise KeyError(
                f"row is missing the availability field {available_at_field!r}; "
                "the dataset declaration does not match the physical table"
            )
        available_at = row[available_at_field]
        if not isinstance(available_at, datetime):
            raise TypeError(
                f"{available_at_field!r} must be a timezone-aware datetime, "
                f"got {type(available_at).__name__}"
            )
        # One attribute read per row, kept because this function takes rows from any caller:
        # the scan's `TIMESTAMPTZ` column cannot hold a naive value, a test fixture can.
        if available_at.tzinfo is None:
            raise ValueError(f"{available_at_field!r} must be a timezone-aware datetime")
        values: dict[str, object] = {}
        for name in declared:
            if name not in row:
                raise KeyError(
                    f"row is missing the declared field {name!r}; a Model reads only what "
                    "it declared, so a missing declared field is a schema error"
                )
            values[name] = row[name]
        observations.append(build(str(row[instrument_field]), available_at, values))
    return tuple(observations)


def _unbounded() -> ConstraintBounds:
    """The bounds a callback sees when no Constraint is registered: no names, no limits."""
    return ConstraintBounds(lower_weights={}, upper_weights={})


class _DeclaredReads:
    """`read(alias, field)` and `rows(alias)` over the aliases a Model declared in `inputs()`.

    Shared by all three contexts because all three roles read the same way -- that sameness is
    the point (`docs/issues/archive/036`), so it is one implementation rather than three that agree today.

    **The grain decides the verb** (design §2.5, owner ruling 2026-09-02). A panel-grain alias is
    read with `read(alias, field)` and returns a 2d `PanelWindow` -- instants x instruments, a
    slice of the panel the run built once. A `rows`-grain alias is read with `rows(alias)` and
    streams `Observation`s, one per (instant, instrument). Each verb refuses the other grain by
    name, so what a dataset IS and what an author receives cannot disagree.
    """

    __slots__ = ()

    # Declared here, supplied by each context's own dataclass fields: the mixin reads them and
    # owns neither.
    window: ModelWindow
    reads: Mapping[str, DatasetInput]

    def _declaration(self, alias: str) -> DatasetInput:
        if not isinstance(alias, str):
            raise TypeError("alias must be a string")
        declared = self.reads.get(alias)
        if declared is None:
            known = ", ".join(sorted(self.reads)) or "nothing"
            raise KeyError(
                f"{alias!r} was not declared in inputs(); this model declared: {known}"
            )
        return declared

    def read(self, alias: str, field: str) -> PanelWindow:
        declared = self._declaration(alias)
        if field not in declared.fields:
            raise KeyError(
                f"{field!r} is not a field of {alias!r}; it declared: {', '.join(declared.fields)}"
            )
        requirements = requirements_for(declared)
        if self.window.grain(requirements[0]) is Grain.ROWS:
            raise TypeError(
                f"{alias!r} is a rows-grain dataset and has no panel; read it with rows({alias!r}) "
                "-- or register the table as grain: instrument_instant if it is one"
            )
        return self.window.panel(requirements, field)

    def rows(self, alias: str) -> tuple:
        declared = self._declaration(alias)
        requirements = requirements_for(declared)
        if self.window.grain(requirements[0]) is not Grain.ROWS:
            raise TypeError(
                f"{alias!r} is a panel-grain dataset; read a field of it with read({alias!r}, "
                "<field>), which returns the instants x instruments window"
            )
        # An alias is one requirement per declared field (`docs/issues/archive/049`) and ONE scan: the
        # window reads every field in one statement and the rows come back already joined on
        # `(instant, instrument)`. The author declared one thing and reads one thing.
        return observations(
            self.window.declared(requirements).rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=declared.fields,
        )


@dataclass(frozen=True, slots=True)
class ConstraintContext(_DeclaredReads, ConstraintCall):
    """What a Constraint may reach, and the third role to reach it the same way.

    Records `126` and `128` gave DataModel and StrategyModel one declaration (`inputs()`) and one
    read verb (`context.read(alias)`). A Constraint was still handed a `ModelWindow` and expected
    to call `window.observations(requirement)` on it -- a framework type and a second read shape,
    for the one extension point whose authoring class the loader would not even accept
    (`docs/issues/archive/036`). This is that third role arriving.

    **No account.** `project` runs before any decision exists, to say what the feasible set is,
    and it never needed one. `monitor` receives an `EconomicAccountView` as its own argument
    instead, so the capability is present exactly where it is used and absent everywhere else.
    """

    window: ModelWindow
    instruments: tuple[str, ...] = ()
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(self.instruments):
            raise ValueError("instruments must be non-empty strings")

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this projection is bounded to."""
        return self.window.evaluation_time


@dataclass(frozen=True, slots=True)
class DataModelContext(_DeclaredReads, DataCall):
    """What a DataModel may reach: a cutoff and its declared reads, and nothing else.

    No account, no venue, no occurrence -- the absence is the definition of the role (architecture
    4.4). The one implementation of `authoring.DataCall`, the way `ConstraintContext` is of
    `ConstraintCall`.
    """

    window: ModelWindow
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this invocation computes at."""
        return self.window.evaluation_time


@dataclass(frozen=True, slots=True)
class StrategyModelContext(_DeclaredReads, StrategyCall):
    """The complete capability surface for one Strategy callback.

    The one implementation of `authoring.StrategyCall`, the way the other two contexts are of
    their calls. `account` is the `EconomicAccountView` the Flow built from the committed
    snapshot and its last valuation -- the same view a monitoring Constraint sees (record `130`).
    The snapshot's `version` is not on it: that is a framework fact the Flow stamps onto the
    intent, and `_ENVELOPE_RESERVED_FIELDS` keeps it off every authored value.
    """

    occurrence: OperationOccurrence
    window: ModelWindow
    account: EconomicAccountView
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)
    constraint_bounds: ConstraintBounds = field(default_factory=_unbounded)
    account_history: AccountHistory = field(default_factory=lambda: AccountHistory((), None))
    """What the Account itself recorded, bounded by this Strategy's declaration.

    Empty unless the Strategy declared an `AccountHistoryInput`. Reading an undeclared field
    raises rather than returning nothing, so a missing declaration fails loudly instead of
    silently disabling a rule that depends on it.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "constraint_bounds", self.constraint_bounds.detached())

    @property
    def occurrence_id(self) -> str:
        return str(self.occurrence.occurrence_id)

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this callback decides at."""
        return self.window.evaluation_time
