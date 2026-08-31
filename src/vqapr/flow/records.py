"""Freeze what a run did into its durable record, and report the contract it honoured.

**Moved out of `vqapr.public` by record `111`, and from `evidence/` to `flow/` by record `113`.**
It lands beside `flow/run_records.py`, which owns `RECORD_FIELDS` and `RunRecordWriter` -- the two
things it builds against. Under `evidence/` it imported three `flow` modules, which is a layer
inversion: `evidence/` is spine, `flow/` is the dispatch loop above it. A run record is a flow
artifact, and this is where it belongs. These build the run record's blocks from a
`FrozenRun` and a `SimulationResult`. They were sitting in the package's documented surface only
because that surface had grown an orchestrator.

Renamed from `_freeze_record` and `_contract_report` on the way. They were private because a
facade should not have had public functions doing this; in their own layer they are ordinary
module-level API, and `flow/orchestration.py` is their caller.
"""

from __future__ import annotations

from vqapr.flow.run import FrozenRun
from vqapr.flow.run_records import RECORD_FIELDS, RunRecordWriter
from vqapr.flow.run_state import LifecycleKind
from vqapr.flow.simulation import SimulationResult


def freeze_record(
    writer: RunRecordWriter,
    result: SimulationResult,
    frozen: FrozenRun,
    as_loaded: str,
    roster: dict[str, object] | None,
) -> None:
    """Write the run's rows and its own facts, so a later process can answer questions about it.

    The rows go first and the record last, because `record.json` existing is what marks the record
    complete. A reader that finds one knows the run reached its end; a run killed midway leaves its
    rows and no record, which `run_ids` correctly declines to list as a finished run.
    """
    recorded = result.final_state.recorder_rows
    for table_id, rows in sorted(recorded.items()):
        writer.append(table_id, rows)

    account = result.final_state.account
    snapshot = None if account is None else account.snapshot

    # AC-R3's five: the facts a later reader cannot reconstruct from the rows alone. Each is built
    # by the function `RECORD_FIELDS` names, so the field set is genuinely ONE list rather than two
    # with a comparison between them -- a field added here without a builder is a KeyError at the
    # comprehension below, not a drift that reaches disk and waits to be noticed.
    builders = {
        "account": lambda: None
        if snapshot is None
        else {
            "version": snapshot.version,
            "cash": snapshot.cash,
            "positions": dict(snapshot.positions),
        },
        "tables": lambda: {
            table_id: {
                "rows": len(rows),
                # Instants, not just rows: a table's row count says how much was written, and the
                # distinct `event_time` count says how often. Research asks the second question
                # and the first cannot answer it.
                #
                # Named `instants` rather than `formations`. "Formation" is portfolio vocabulary,
                # and this counter is applied to every table -- including `vqapr.fill`, where a
                # formation is not a thing that happens. A reader who could not work out what it
                # counted said so (`docs/issues/024`), and the honest answer is the one in the
                # expression: how many distinct instants this table has rows for.
                "instants": len({str(row.get("event_time")) for row in rows}),
            }
            for table_id, rows in sorted(recorded.items())
        },
        "contract": lambda: contract_report(result),
        # What ran, not what was registered. These agree unless a component was edited after
        # registration, and that difference is the whole signal: a strategy that ran 47 times
        # across 12 distinct `source_digest` values was edited 11 times, which is a direct
        # overfitting tell that a new component_id per edit would have scattered.
        "source_digest": lambda: as_loaded,
        # The declaration this run froze against, kept so the pair stays legible: equal to
        # `source_digest` when nothing moved, different exactly when it did.
        "declared_digest": lambda: str(frozen.identity),
        # Which roster this run read, and `None` when it read none. STATED, never compared -- a
        # roster grows as a matter of course, so a run refused for reading a different one than
        # yesterday would be refused every morning. What a run treated each instrument as is
        # testified to per fill by `Fill.kind`; this says which declaration produced those
        # categories, and `None` says the run never knew them.
        "roster": lambda: roster,
        "period": lambda: {
            "start": frozen.start,
            "end": frozen.end,
            "occurrences": len(result.occurrences),
        },
    }

    # `run_id` is stamped by the writer itself, so it is the one field this does not supply.
    writer.finish({field: builders[field]() for field in RECORD_FIELDS if field != "run_id"})


def contract_report(result: SimulationResult) -> dict[str, object]:
    """What the run's constraints promised, and how often each was actually checked.

    `held` and `checked` are two different numbers, and conflating them hides the case that matters
    most: a declaration checked zero times is not a declaration that held. It is one nobody asked
    about, and reporting that as `ok` would be the strongest false assurance this record could
    carry. So a constraint with `checked == 0` reports `ok: false` with a `cause` saying exactly
    that.

    Scope, stated rather than implied: this reports the CONSTRAINTS a run declared. AC-R6 also
    names `weights`/`forms`/`records`, which are the authoring contract's declarations -- they do
    not exist yet, and inventing entries for them here would report a promise nobody made. They
    join this block when that contract lands.
    """

    findings: dict[str, dict[str, int]] = {}
    for entry in getattr(result.final_state, "lifecycle_trace", ()):
        evidence = getattr(entry, "evidence", None)
        for item in getattr(evidence, "intended", ()) or ():
            finding = getattr(item, "finding", None)
            constraint_id = str(getattr(finding, "constraint_id", "") or "")
            if not constraint_id:
                continue
            counts = findings.setdefault(constraint_id, {"held": 0, "checked": 0})
            counts["checked"] += 1
            if getattr(finding, "passed", False):
                counts["held"] += 1

    accepted = sum(
        1
        for entry in getattr(result.final_state, "lifecycle_trace", ())
        if getattr(entry, "kind", None) is LifecycleKind.ACCEPTED_INTENT
    )
    report: dict[str, object] = {}
    for constraint_id, counts in sorted(findings.items()):
        violations = counts["checked"] - counts["held"]
        entry: dict[str, object] = {
            "held": counts["held"],
            "checked": counts["checked"],
            "ok": violations == 0 and counts["checked"] > 0,
        }
        if violations:
            entry["cause"] = f"{violations} of {counts['checked']} check(s) did not hold"
            entry["fix"] = (
                f"loosen {constraint_id} to a bound the strategy can meet, or change the "
                "strategy so its intents satisfy it"
            )
        elif counts["checked"] == 0:
            entry["cause"] = "declared but never checked, so nothing was proven about it"
            entry["fix"] = "remove the declaration, or run over a period where it is exercised"
        report[constraint_id] = entry

    # A run that accepted intents while checking no constraint is not a clean run; it is a run
    # nobody constrained. Saying so is the point of reporting counts rather than a verdict.
    report["accepted_intents"] = accepted
    return report
