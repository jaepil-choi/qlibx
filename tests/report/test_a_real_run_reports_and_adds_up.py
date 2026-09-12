"""The shipped sample journey, reported: the identities hold on a record a real run wrote.

The hand-checked fixture beside this file proves the arithmetic; this proves the door -- the
row shapes the recorder actually writes (`Decimal` in every table since record `264`, a
version-0 valuation before any fill) reach the same identities.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import tests.sample.journey as journey
from vqapr.public import Workspace, freeze, read_strategy_table, run_report
from vqapr.public import run as execute_run
from vqapr.record import COMPACT_FILENAME, TABLES_DIRECTORY, record_directory, strategy_refs


@pytest.mark.slow
def test_the_sample_journeys_report_adds_up(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    journey.install(project)
    frozen = freeze(project, Workspace.open(project).run_definition(journey.RUN_ID))
    store = tmp_path / "store"
    execute_run(project, frozen, store_root=store)

    report = run_report(store, journey.RUN_ID)

    (strategy,) = report.strategies.values()
    assert strategy.positions_recorded is True
    assert strategy.omitted == {
        "compliance": "vqapr.monitoring is empty: the run declared no compliance rule"
    }
    performance = strategy.performance
    assert performance.periods_per_year == 252 and performance.periods > 500
    assert performance.initial_nav == Decimal(100_000_000)
    assert performance.nav.values[0] == Decimal(100_000_000), (
        "the first valuation is the initial book"
    )
    attribution = strategy.attribution
    assert attribution is not None
    assert all(residual == 0 for residual in attribution.residual), "every held name was marked"
    assert attribution.total_pnl == performance.nav.values[-1] - performance.nav.values[0]
    assert attribution.short_pnl == 0, "the sample is long-only"
    trading = strategy.trading
    assert trading.fills_outside_periods == 0
    assert trading.fills["orders"] == trading.fills["dealt"] + trading.fills["zero_dealt"]
    assert trading.rebalances == len(trading.intended_turnover.values)
    assert strategy.intent is not None and strategy.intent.weights_scored > 0
    assert report.headline[0].strategy_id == "sample-reversal-5d"
    assert report.correlation is None, "one strategy has nothing to correlate with"
    json.dumps(report.as_record())

    # Record `264`: the fill and weight numbers are recorded as numbers, tagged in the parquet,
    # and read back as `Decimal` like `nav` beside them -- not as the text three exporters broke on.
    fills = list(read_strategy_table(store, journey.RUN_ID, "vqapr.fill"))
    weights = list(read_strategy_table(store, journey.RUN_ID, "vqapr.weight"))
    assert fills and weights
    for column in ("requested_quantity", "dealt_quantity", "cash_delta", "commission", "tax"):
        assert all(isinstance(row[column], Decimal) for row in fills), column
    for column in ("price", "sized_quantity"):  # null on a refused fill; `sized_quantity`: 261
        assert all(row[column] is None or isinstance(row[column], Decimal) for row in fills)
    assert all(isinstance(row["weight"], Decimal) for row in weights)
    (ref,) = strategy_refs(store, journey.RUN_ID)
    tables = record_directory(store, journey.RUN_ID, ref) / TABLES_DIRECTORY
    decimal = {b"vqapr.type": b"decimal"}
    assert pq.read_schema(tables / "vqapr.fill" / COMPACT_FILENAME).field("commission").metadata == decimal
    assert pq.read_schema(tables / "vqapr.weight" / COMPACT_FILENAME).field("weight").metadata == decimal
