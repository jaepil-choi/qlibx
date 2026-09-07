"""The door: a report from a record on disk.

`strategy_report` opens one strategy's record and its four tables through `vqapr.flow.record`
(the same reader `vqapr show strategy --table` uses) and hands the rows to `measure`.
`run_report` does that for every strategy of a run and adds what only the run can answer: the
headline table, the correlation of period returns, and each strategy against a benchmark
strategy of the same run.

`root` is the store -- the `store_root` `vqapr run` prints, `<project>/.vqapr` unless moved --
not the project directory, exactly as for `read_strategy_table`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from vqapr.flow.context import FRAMEWORK_TABLES
from vqapr.flow.record import (
    read_run_record,
    read_strategy_record,
    read_table,
    resolve_strategy_ref,
    strategy_refs,
)
from vqapr.report import measure
from vqapr.report.document import RunReport, StrategyReport

__all__ = ["run_report", "strategy_report"]

ACCOUNT_TABLE, FILL_TABLE, MONITORING_TABLE, WEIGHT_TABLE = (
    next(table for table in FRAMEWORK_TABLES if table.endswith(suffix))
    for suffix in ("account", "fill", "monitoring", "weight")
)


def strategy_report(
    root: Path,
    run_id: str,
    strategy_ref: str | None = None,
    *,
    periods_per_year: int | None = None,
    risk_free_annual: Decimal = Decimal(0),
) -> StrategyReport:
    """One strategy's report from its record.

    `strategy_ref` resolves the way `read_strategy_table`'s does: `<strategy-id>@<fp8>`, the bare
    `<strategy-id>` when one record of it exists, or `None` when the run holds one strategy.
    `periods_per_year` defaults to what the valuation grid implies (`infer_periods_per_year`)
    and the report says which. `risk_free_annual` is a simple annual rate the record does not
    hold; zero unless given.
    """
    resolved = resolve_strategy_ref(root, run_id, strategy_ref)
    if resolved is None:
        raise ValueError(
            f"run {run_id!r} records tables of its own and no strategy; a report needs a "
            "strategy record"
        )
    record = read_strategy_record(root, run_id, resolved)
    run = read_run_record(root, run_id)

    initial = run.get("initial_account") or {}
    initial_nav = (
        Decimal(str(initial["cash"]))
        if initial.get("cash") is not None and not initial.get("positions")
        else None
    )
    grid = measure.opening(
        measure.valuations(read_table(root, run_id, ACCOUNT_TABLE, resolved)),
        initial_cash=initial_nav,
        period_start=_instant((run.get("period") or {}).get("start")),
    )
    if not grid:
        raise ValueError(f"{run_id!r}/{resolved!r} recorded no valuation; nothing to report")
    fill_rows = list(read_table(root, run_id, FILL_TABLE, resolved))
    placed = measure.fills(fill_rows)
    intended = measure.decisions(read_table(root, run_id, WEIGHT_TABLE, resolved))
    monitoring_rows = list(read_table(root, run_id, MONITORING_TABLE, resolved))

    # Positions are recorded unless the run was told not to (`--no-account-positions`). A book
    # with no position row and nothing ever dealt is simply empty; one with fills dealt and no
    # position row was recorded without them, and the sections that need them say so.
    dealt_anything = any(fill.dealt != 0 for fill in placed)
    positions_recorded = any(valuation.positions for valuation in grid) or not dealt_anything

    if periods_per_year is None:
        periods_per_year = measure.infer_periods_per_year([valuation.at for valuation in grid])
        source = "inferred"
    else:
        source = "given"

    omitted: dict[str, str] = {}
    performance = measure.performance(
        grid,
        periods_per_year=periods_per_year,
        periods_per_year_source=source,
        risk_free_annual=risk_free_annual,
        initial_nav=initial_nav,
    )
    if positions_recorded:
        book = measure.book(grid)
        attribution = measure.attribution(grid, placed)
        intent = measure.intent(grid, intended)
    else:
        book = attribution = intent = None
        why = (
            f"{ACCOUNT_TABLE} holds only the {measure.ACCOUNT_ROW} row (the run was recorded "
            "without positions), so the book cannot be read back"
        )
        omitted.update({"book": why, "attribution": why, "intent": why, "trading.holding": why})
    trading = measure.trading(
        grid,
        placed,
        fill_rows,
        intended,
        periods_per_year=periods_per_year,
        positions_recorded=positions_recorded,
    )
    if monitoring_rows:
        compliance = measure.compliance(monitoring_rows)
    else:
        compliance = None
        omitted["compliance"] = (
            f"{MONITORING_TABLE} is empty: the strategy declared no constraint"
            if not record.get("constraints")
            else f"{MONITORING_TABLE} is empty although constraints were declared"
        )
    return StrategyReport(
        run_id=run_id,
        strategy_ref=resolved,
        strategy_id=str(record["strategy_id"]),
        period=dict(record.get("period") or {}),
        positions_recorded=positions_recorded,
        omitted=omitted,
        performance=performance,
        book=book,
        attribution=attribution,
        trading=trading,
        intent=intent,
        compliance=compliance,
    )


def run_report(
    root: Path,
    run_id: str,
    *,
    benchmark: str | None = None,
    periods_per_year: int | None = None,
    risk_free_annual: Decimal = Decimal(0),
) -> RunReport:
    """Every finished strategy of a run, side by side.

    `benchmark` names a strategy of the same run (a ref or a bare id); every other strategy is
    then also reported against it. A benchmark outside the run -- an index level, say -- is not
    something the record holds, and is not invented here.
    """
    refs = strategy_refs(root, run_id)
    if not refs:
        raise ValueError(f"run {run_id!r} has no finished strategy record under {root}")
    reports = {
        ref: strategy_report(
            root, run_id, ref, periods_per_year=periods_per_year, risk_free_annual=risk_free_annual
        )
        for ref in refs
    }
    ordered = list(reports.values())
    relative = []
    if benchmark is not None:
        resolved = resolve_strategy_ref(root, run_id, benchmark)
        if resolved not in reports:
            raise ValueError(
                f"benchmark {benchmark!r} is not a finished strategy of {run_id!r}; "
                f"finished: {', '.join(refs)}"
            )
        base = reports[resolved]
        relative = [measure.relative(report, base) for report in ordered if report is not base]
    return RunReport(
        run_id=run_id,
        strategies=reports,
        headline=[measure.headline(report) for report in ordered],
        correlation=measure.correlation(ordered),
        relative=relative,
    )


def _instant(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None
