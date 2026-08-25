"""A thin adapter letting `Project` drive the retained execution/valuation engine.

This translates between the supported `Project` surface and the legacy
`preflight_run`/`run` pair; it does not reimplement any of their behavior. The heavier
`vqapr.flow` and `vqapr.workspace` layers are imported lazily inside each function body
so that importing this module alone never drags them into `sys.modules` -
`tests/boundaries/test_capability_absence.py` enforces exactly that discipline for leaf
modules, and this module must not breach it either.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType


def frozen_run_for(root: Path | str, definition: object) -> object:
    """Resolve the legacy `Workspace` for `root` and preflight `definition` against it.

    Returns the `FrozenRun` the retained engine's `run()` expects. `definition` is
    whatever `preflight_run` itself validates; this function does no extra checking
    beyond what resolving the workspace requires.
    """
    from vqapr.flow.preflight import preflight_run
    from vqapr.workspace import Workspace

    workspace = Workspace.open(root)
    return preflight_run(workspace, definition)


def execute_frozen_run(root: Path | str, frozen: object) -> object:
    """Execute a preflight-produced `FrozenRun` through the retained engine, unchanged."""
    from vqapr.public import run

    return run(root, frozen)


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulationSummary:
    """What a caller can act on from a `SimulationResult`, without raw engine internals."""

    occurrences: int
    accepted_intents: int
    executions: int
    final_account_version: int | None

    def __post_init__(self) -> None:
        for name in ("occurrences", "accepted_intents", "executions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.final_account_version is not None:
            if isinstance(self.final_account_version, bool) or not isinstance(
                self.final_account_version, int
            ):
                raise TypeError("final_account_version must be an integer or None")
            if self.final_account_version < 0:
                raise ValueError("final_account_version must be non-negative")


def summarize(result: object) -> SimulationSummary:
    """Project a `SimulationResult` onto the bounded `SimulationSummary` a caller sees.

    `result.occurrences` mixes `OccurrenceTrace` (one entry per dispatched occurrence)
    with `DueExecutionTrace` (one entry per completed post-decision execution). Both are
    counted toward `occurrences`.

    `accepted_intents` is read from the engine's own `final_state.lifecycle_trace` rather
    than by inspecting `OccurrenceTrace.result`. That field is annotated `object` and
    carries a decision only for a callback dispatch, so an isinstance probe against it
    silently reported zero on a real run that had in fact accepted 34 intents - the
    lifecycle trace is the engine's authoritative record, so it is what gets counted.
    """
    from vqapr.flow.run_state import LifecycleKind
    from vqapr.flow.simulation import DueExecutionTrace

    occurrences = tuple(result.occurrences)
    accepted_intents = sum(
        1
        for entry in result.final_state.lifecycle_trace
        if entry.kind is LifecycleKind.ACCEPTED_INTENT
    )
    executions = sum(1 for trace in occurrences if isinstance(trace, DueExecutionTrace))

    final_account_version: int | None = None
    account = result.final_state.account
    if account is not None:
        final_account_version = account.snapshot.version

    return SimulationSummary(
        occurrences=len(occurrences),
        accepted_intents=accepted_intents,
        executions=executions,
        final_account_version=final_account_version,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RunAccount:
    """The committed account a run ended on, as bounded public values."""

    version: int
    cash: Decimal
    positions: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))

    def quantity(self, instrument_id: str) -> Decimal:
        """The held quantity, or zero for an instrument this run never held."""
        return self.positions.get(instrument_id, Decimal(0))


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedRun:
    """A finished run, readable without reaching into the engine.

    `SimulationSummary` deliberately exposes only counts so a caller cannot reach raw
    engine internals. That turned out too narrow: a run whose costs and fills you cannot
    inspect is not usable for research, which is what this exposes - the committed
    account and the recorder tables the run actually produced, as detached values.
    """

    summary: SimulationSummary
    account: RunAccount | None
    tables: Mapping[str, tuple[Mapping[str, object], ...]]
    # The engine result, retained so a run's allocation can be published without the
    # caller reaching for it. It is deliberately not part of the readable surface: every
    # value a caller needs is projected above, and handing back the raw result would make
    # the bounded projection pointless.
    _result: object = None

    def publish_allocation(self, root, dataset_id: str, *, value_field: str = "weight"):
        """Publish this run's accepted allocations as a readable dataset.

        A run that cannot publish what it decided is not usable for research: the whole
        point of the factor pipeline is that one run's allocation becomes the next run's
        input. The evidence travels from the result rather than from the caller, so a
        publication can only ever describe a run that actually happened.
        """
        from vqapr.public import AllocationPublicationSpec, publish_run_allocation

        if self._result is None:
            raise ValueError(
                "this CompletedRun carries no result to publish; it was built for "
                "readback only"
            )
        return publish_run_allocation(
            root,
            AllocationPublicationSpec.of(dataset_id, value_field=value_field),
            self._result,
        )

    def publish_record(
        self, root, dataset_id: str, *, table_id: str, value_fields: tuple[str, ...]
    ):
        """Publish one of this run's recorder tables as a readable dataset.

        The same reasoning as `publish_allocation`: a recorded table that cannot be read
        back is evidence nobody can check.
        """
        from vqapr.public import RunRecordSpec, publish_run_record

        if self._result is None:
            raise ValueError(
                "this CompletedRun carries no result to publish; it was built for "
                "readback only"
            )
        return publish_run_record(
            root,
            RunRecordSpec.of(dataset_id, table_id=table_id, value_fields=value_fields),
            self._result,
        )

    def table(self, table_id: str) -> tuple[Mapping[str, object], ...]:
        """One recorder table's rows. Raises for a table this run never recorded."""
        if table_id not in self.tables:
            available = sorted(self.tables)
            raise KeyError(f"run recorded no table {table_id!r}; recorded: {available}")
        return self.tables[table_id]

    def fills(self) -> tuple[Mapping[str, object], ...]:
        """Every recorded fill. Empty when the run executed nothing."""
        return self.tables.get("vqapr.fill", ())


def complete(result: object) -> CompletedRun:
    """Project a `SimulationResult` onto the public run-readback value."""
    state = result.final_state
    account_state = state.account
    account = None
    if account_state is not None:
        snapshot = account_state.snapshot
        account = RunAccount(
            version=snapshot.version,
            cash=snapshot.cash,
            positions=dict(snapshot.positions),
        )
    tables = {
        name: tuple(dict(row) for row in rows)
        for name, rows in state.recorder_rows.items()
    }
    return CompletedRun(
        summary=summarize(result),
        account=account,
        tables=MappingProxyType(tables),
        _result=result,
    )
