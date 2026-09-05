"""Freeze what a run did into its durable records, and report the contract each strategy honoured.

**Two records since record `139`** (design `docs/design/the-panel-the-surface-and-the-run.md`
§4.2). `run.json` is configuration: what every strategy in the run shared -- universe, period,
venue, execution input and its fill convention (`docs/issues/034`), the initial account
declaration, the datasets read and their source digests (testbed A7), and which strategies the
run names. `strategy.json`, one per `strategies/<id>@<fp8>/`, is output: the component that ran,
its own fingerprint as registered and as loaded, its constraints, its contract report, its final
account, its tables, its period, the roster it read.

**Moved out of `vqapr.public` by record `111`, and from `evidence/` to `flow/` by record `113`.**
It lands beside `flow/run_records.py`, which owns the field sets and the writers -- the two things
this builds against. A run record is a flow artifact, and this is where it belongs.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from vqapr.flow.datamodel import DataModelResult
from vqapr.flow.run import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.run_records import (
    DATAMODEL_KIND,
    RUN_JSON_FIELDS,
    STRATEGY_KIND,
    RunRecordWriter,
    record_fields,
    write_run_record,
)
from vqapr.flow.run_state import LifecycleKind
from vqapr.flow.simulation import SimulationResult


def freeze_run_record(root: Path, frozen: FrozenRun, *, source_digests: Mapping[str, str]) -> Path:
    """Write `run.json`: the configuration every strategy of this run shares.

    Written BEFORE any strategy runs, so a run killed midway still says what it attempted, and
    identical for every process that runs a strategy of this run -- which is why it needs no lock:
    two writers write the same bytes. A run whose configuration changed since a record was written
    under this id is refused by `write_run_record`, naming both digests.

    `source_digests` are the physical digests of the sources the run reads, keyed by source id:
    a registration keeps an id and a path, and nothing pinned the bytes behind them (A7).
    """
    execution = frozen.execution_input
    builders = {
        "declared_digest": lambda: str(frozen.identity),
        "instruments": lambda: list(frozen.instruments),
        "period": lambda: {"start": frozen.start, "end": frozen.end},
        "exchange": lambda: (
            None
            if frozen.exchange is None
            else {
                "component_id": str(frozen.exchange.component_id),
                "fingerprint": frozen.exchange.fingerprint,
            }
        ),
        # `034` closes here: which convention this run filled under, in the record's own words.
        "execution_input": lambda: (
            None
            if execution is None
            else {
                "execution_input_id": str(execution.execution_input_id),
                "source_id": str(execution.table.source.source_id),
                "trade_at_field": execution.table.trade_at_field,
                "price_fields": dict(execution.table.price_fields),
                "fill": {
                    "selector": execution.fill.selector.value,
                    "local_time": execution.fill.local_time.isoformat(),
                    "timezone": execution.fill.timezone,
                    "trade_price": execution.fill.trade_price,
                    "declaration_identity": execution.fill.declaration_identity,
                },
            }
        ),
        "initial_account": lambda: (
            None
            if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None
            else {
                "mode": frozen.initial_account_mode.value,
                "version": frozen.initial_account_snapshot.version,
                "cash": frozen.initial_account_snapshot.cash,
                "positions": dict(frozen.initial_account_snapshot.positions),
            }
        ),
        "datasets": lambda: [
            {
                "dataset_id": str(dataset.dataset_id),
                "source_id": str(dataset.source),
                "grain": None if dataset.grain is None else dataset.grain.value,
                "source_digest": source_digests.get(str(dataset.source)),
            }
            for dataset in frozen.datasets
        ],
        "strategies": lambda: [
            {"component_id": layer.component_id, "record": layer.record_ref}
            for layer in frozen.strategies
        ],
        # A run holds one kind (record `148`); the other list is empty, and stays in the record
        # so a reader never has to know which kind it is holding to ask.
        "datamodels": lambda: [
            {
                "component_id": layer.component_id,
                "record": layer.record_ref,
                "dataset_id": layer.dataset_id,
            }
            for layer in frozen.datamodels
        ],
    }
    return write_run_record(
        root,
        frozen.run_id,
        {field: builders[field]() for field in RUN_JSON_FIELDS if field != "run_id"},
    )


def freeze_strategy_record(
    writer: RunRecordWriter,
    result: SimulationResult,
    frozen: FrozenRun,
    layer: FrozenStrategy,
    as_loaded: Mapping[str, str],
    roster: dict[str, object] | None,
) -> None:
    """Write one strategy's rows and its own facts, so a later process can read them.

    The rows go first and the record last, because `strategy.json` existing is what marks the
    record complete. A reader that finds one knows the strategy reached its end; one killed midway
    leaves its rows and no record, which `strategy_refs` correctly declines to list as finished.
    """
    # A run with a store streams its rows to this writer as each occurrence is accepted, so
    # `recorder_rows` is empty here and everything is already on disk. A result assembled without
    # a sink still carries its rows, and they are appended now. Either way the writer counted what
    # it wrote, which is what the `tables` block below reports.
    recorded = result.final_state.recorder_rows
    for table_id, rows in sorted(recorded.items()):
        writer.append(table_id, rows)

    account = result.final_state.account
    snapshot = None if account is None else account.snapshot
    component = layer.config.component

    # Each is built by the function `record_fields` names, so the field set is genuinely ONE list
    # rather than two with a comparison between them -- a field added here without a builder is a
    # KeyError at the comprehension below, not a drift that reaches disk and waits to be noticed.
    builders = {
        "strategy_id": lambda: layer.component_id,
        # The registered fingerprint, in full; the directory name carries its first eight.
        "fingerprint": lambda: component.fingerprint,
        "component": lambda: {
            "component_id": layer.component_id,
            "path": str(component.path),
            "object_name": component.object_name,
            "config": dict(component.config),
            "fingerprint": component.fingerprint,
        },
        "agenda": lambda: {
            "agenda_id": str(layer.agenda.agenda_id),
            "content_identity": layer.agenda.content_identity,
            "occurrences": len(layer.agenda.occurrences),
        },
        "constraints": lambda: [
            {"component_id": str(constraint.component_id), "fingerprint": constraint.fingerprint}
            for constraint in layer.constraints.constraints
        ],
        "account": lambda: (
            None
            if snapshot is None
            else {
                "version": snapshot.version,
                "cash": snapshot.cash,
                "positions": dict(snapshot.positions),
            }
        ),
        # Rows and instants per table, counted by the writer as it appended them. Instants, not
        # just rows: a table's row count says how much was written, and the distinct `event_time`
        # count says how often; research asks the second question and the first cannot answer it.
        "tables": writer.counts,
        "contract": lambda: contract_report(result),
        # What ran, not what was registered -- PER COMPONENT rather than folded (design §4.2).
        # `fingerprint` above is what was registered; this is the fingerprint of the bytes on disk
        # when they were loaded. They agree unless the component was edited after registration,
        # and that difference is the whole signal (`docs/issues/009`, `023`): a strategy that ran
        # 47 times under 12 distinct loaded fingerprints was edited 11 times, which is a direct
        # overfitting tell that a new component_id per edit would have scattered.
        "source_digest": lambda: dict(as_loaded),
        # The declaration this strategy froze against: its own identity, not the run's.
        "declared_digest": lambda: str(layer.identity),
        # Which roster this run read, and `None` when it read none. STATED, never compared -- a
        # roster grows as a matter of course, so a run refused for reading a different one than
        # yesterday would be refused every morning.
        "roster": lambda: roster,
        "period": lambda: {
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
        },
        # Where the wall clock went, by phase (`docs/issues/068`): the loop's `total`, the
        # `callback` side (window and decide), the `due` side, and each due stage by name.
        # Seconds, rounded to the microsecond so the record is not a float's full expansion.
        "timing": lambda: {phase: round(seconds, 6) for phase, seconds in result.timing.items()},
    }

    # `run_id` and `strategy_ref` are stamped by the writer itself.
    writer.finish(
        {
            field: builders[field]()
            for field in record_fields(STRATEGY_KIND)
            if field not in ("run_id", "strategy_ref")
        },
        kind=STRATEGY_KIND,
    )


def freeze_datamodel_record(
    writer: RunRecordWriter,
    result: DataModelResult,
    frozen: FrozenRun,
    layer: FrozenDataModel,
    as_loaded: Mapping[str, str],
) -> None:
    """Write one datamodel's facts, last, so a later process can read them (record `148`).

    The rows are not here: they are the dataset the run registered, under
    `.vqapr/materialized/<dataset_id>/`, and `dataset_id` names it. What this holds is what a
    reader cannot rebuild from that dataset -- which component wrote it, registered and as
    loaded, on which sessions, reading what -- and one line per session rather than the
    per-instrument lineage `059` measured at 478 MB.
    """
    component = layer.component
    times = [trace.evaluation_time for trace in result.occurrences]
    builders = {
        "datamodel_id": lambda: layer.component_id,
        "fingerprint": lambda: component.fingerprint,
        "component": lambda: {
            "component_id": layer.component_id,
            "path": str(component.path),
            "object_name": component.object_name,
            "config": dict(component.config),
            "fingerprint": component.fingerprint,
        },
        "agenda": lambda: {
            "agenda_id": str(layer.agenda.agenda_id),
            "content_identity": layer.agenda.content_identity,
            "occurrences": len(layer.agenda.occurrences),
        },
        "dataset_id": lambda: layer.dataset_id,
        "value_fields": lambda: list(layer.value_fields),
        "rows": lambda: result.rows,
        "sessions": lambda: [
            {
                "evaluation_time": trace.evaluation_time,
                "output_available_at": trace.output_available_at,
                "row_count": trace.row_count,
            }
            for trace in result.occurrences
        ],
        "source_digest": lambda: dict(as_loaded),
        "declared_digest": lambda: str(layer.identity),
        "period": lambda: {
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
            "first": min(times) if times else None,
            "last": max(times) if times else None,
        },
    }
    writer.finish(
        {
            field: builders[field]()
            for field in record_fields(DATAMODEL_KIND)
            if field not in ("run_id", "datamodel_ref")
        },
        kind=DATAMODEL_KIND,
    )


def contract_report(result: SimulationResult) -> dict[str, object]:
    """What the strategy's constraints promised, and how often each was actually observed to hold.

    `held` and `checked` are two different numbers, and conflating them hides the case that matters
    most: a declaration checked zero times is not a declaration that held. It is one nobody asked
    about, and reporting that as `ok` would be the strongest false assurance this record could
    carry. So a constraint with `checked == 0` reports `ok: false` with a `cause` saying exactly
    that.

    **These count monitoring observations of the committed account.** They used to be meant to
    count judgements of the decision, and that member no longer exists: whether a limit held is a
    question about the book, not about the plan (PRD 7.1).

    **And they used to count nothing at all.** This walked the run's lifecycle entries asking each
    for an `evidence` attribute, but a lifecycle entry carries `kind` and `detail` and the evidence
    is the `detail` -- so the lookup returned `None` every time and the loop never ran
    (`docs/issues/051`).

    Scope, stated rather than implied: this reports the CONSTRAINTS a strategy declared. AC-R6 also
    names `weights`/`forms`/`records`, which are the authoring contract's declarations -- they do
    not exist yet, and inventing entries for them here would report a promise nobody made.
    """

    # Three populations, not one (`docs/issues/086`): what the author's own comparison held,
    # what it failed inside the framework's tolerance, and what it failed beyond it. The run that
    # filed the issue had 40 quantisation residues (worst 0.01%p) and one real breach (4.89%p),
    # and `held 42/82` reported them as one fact. `ok` turns on `breached` alone; the other two
    # counts and their worst excesses are filed beside it so a generous tolerance hides nothing.
    findings: dict[str, dict[str, object]] = {}
    for trace in getattr(result, "occurrences", ()):
        report = getattr(getattr(trace, "result", None), "report", None)
        for stamped in getattr(report, "findings", ()) or ():
            constraint_id = str(getattr(stamped, "constraint_id", "") or "")
            if not constraint_id:
                continue
            counts = findings.setdefault(
                constraint_id,
                {
                    "held": 0,
                    "within_tolerance": 0,
                    "breached": 0,
                    "checked": 0,
                    "tolerance": Decimal(0),
                    "worst_within": None,
                    "worst_breached": None,
                },
            )
            counts["checked"] += 1  # type: ignore[operator]
            verdict = getattr(stamped, "verdict", "held" if stamped.passed else "breached")
            counts[verdict] += 1  # type: ignore[operator]
            tolerance = getattr(stamped, "tolerance", None)
            if isinstance(tolerance, Decimal) and tolerance > counts["tolerance"]:  # type: ignore[operator]
                counts["tolerance"] = tolerance
            if verdict == "held":
                continue
            key = "worst_within" if verdict == "within_tolerance" else "worst_breached"
            excess = getattr(stamped, "excess", Decimal(0))
            worst = counts[key]
            if worst is None or excess > worst:  # type: ignore[operator]
                counts[key] = excess

    accepted = sum(
        1
        for entry in getattr(result.final_state, "lifecycle_trace", ())
        if getattr(entry, "kind", None) is LifecycleKind.ACCEPTED_INTENT
    )
    report: dict[str, object] = {}
    for constraint_id, counts in sorted(findings.items()):
        checked = int(counts["checked"])  # type: ignore[call-overload]
        breached = int(counts["breached"])  # type: ignore[call-overload]
        entry: dict[str, object] = {
            "held": counts["held"],
            "within_tolerance": counts["within_tolerance"],
            "breached": breached,
            "checked": checked,
            "tolerance": str(counts["tolerance"]),
            "worst_within": None if counts["worst_within"] is None else str(counts["worst_within"]),
            "worst_breached": (
                None if counts["worst_breached"] is None else str(counts["worst_breached"])
            ),
            "ok": breached == 0 and checked > 0,
        }
        if breached:
            entry["cause"] = (
                f"{breached} of {checked} check(s) breached beyond the tolerance "
                f"{counts['tolerance']} (worst excess {counts['worst_breached']})"
            )
            entry["fix"] = (
                f"change the strategy so what it holds satisfies {constraint_id}, loosen the "
                "bound, or -- if these are execution residue and not intent -- raise the "
                "constraint's `tolerance`"
            )
        elif checked == 0:
            entry["cause"] = "declared but never checked, so nothing was proven about it"
            entry["fix"] = "remove the declaration, or run over a period where it is exercised"
        report[constraint_id] = entry

    # A run that accepted intents while checking no constraint is not a clean run; it is a run
    # nobody constrained. Saying so is the point of reporting counts rather than a verdict.
    report["accepted_intents"] = accepted
    return report
