"""The shipped sample journey, reported: the identities hold on a record a real run wrote.

The hand-checked fixture beside this file proves the arithmetic; this proves the door -- the
row shapes the recorder actually writes (text in the fill and weight tables, `Decimal` in the
account table, a version-0 valuation before any fill) reach the same identities.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import tests.sample.journey as journey
from vqapr.public import Workspace, preflight_run, run_report
from vqapr.public import run as execute_run


@pytest.mark.slow
def test_the_sample_journeys_report_adds_up(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    journey.install(project)
    frozen = preflight_run(project, Workspace.open(project).run_definition(journey.RUN_ID))
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
