"""The sample panel is deliberately unbalanced, and that shape is the thing under test.

A balanced panel would let a Strategy look correct while assuming every instrument exists on every
session. These tests pin the two cases that break that assumption and the fact that the Strategy
resolves neither of them itself.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tests.sample import journey
from vqapr.agent.sample.reversal_5d import LOOKBACK, SampleReversal5d


@pytest.fixture(scope="module")
def panel(tmp_path_factory):
    """The sample as `vqapr new sample` writes it, installed once for this module: the packaged
    synthetic panel plus `panel.json`, which says which name lists late and which stops early."""
    return journey.install(tmp_path_factory.mktemp("sample-panel"))


def _rows(path: Path, instrument: str, field: str) -> list:
    return sorted(
        row[field] for row in pq.read_table(path).to_pylist() if row["instrument"] == instrument
    )


@pytest.mark.slow
def test_the_panel_holds_ten_named_instruments(panel) -> None:
    assert len(panel.instruments) == 10
    assert len(set(panel.instruments)) == 10


@pytest.mark.slow
def test_one_instrument_lists_after_the_window_opens(panel) -> None:
    """A late lister has no rows at the start, which is what removes it from early sessions."""
    observed = _rows(panel.observations, panel.late_listed, "available_at")
    assert len(observed) == panel.session_count - panel.panel["late_sessions"]
    assert observed[-1] == max(
        row["available_at"] for row in pq.read_table(panel.observations).to_pylist()
    )


@pytest.mark.slow
def test_one_instrument_stops_before_the_window_closes(panel) -> None:
    observed = _rows(panel.observations, panel.delisted, "available_at")
    assert len(observed) == panel.session_count - panel.panel["dead_sessions"]


@pytest.mark.slow
def test_the_delisted_name_keeps_a_tradable_tail(panel) -> None:
    """A position is closed after the Strategy drops the name, and that fill needs a price."""
    observed = _rows(panel.observations, panel.delisted, "available_at")
    tradable = _rows(panel.execution, panel.delisted, "trade_at")
    assert len(tradable) == len(observed) + panel.panel["wind_down_sessions"]
    assert max(tradable) > max(observed)


@pytest.mark.slow
def test_prices_are_exact(panel) -> None:
    """Row scalars keep their source type, so a float source would make the callback inexact."""
    row = pq.read_table(panel.observations).to_pylist()[0]
    assert isinstance(row["close"], Decimal)


@pytest.mark.slow
def test_the_strategy_declares_the_lookback_it_reads(panel) -> None:
    declared = SampleReversal5d().inputs()["prices"]
    assert declared.lookback.rows == LOOKBACK
    assert LOOKBACK == 6, "a five-day return compares six observations"


def test_the_strategy_never_inspects_listing_status() -> None:
    """Tradability is an execution-time fact; a callback that asks about it is guessing."""
    source = Path(inspect.getfile(SampleReversal5d))
    text = source.read_text(encoding="utf-8")
    body = text.split("def decide", 1)[1]
    for forbidden in ("is_tradable", "listed", "delist", "halt", "max_available_at"):
        assert forbidden not in body


@pytest.mark.slow
def test_the_sample_journey_runs_end_to_end(tmp_path: Path) -> None:
    """The reference journey an agent copies must actually run.

    `reversal_5d` is written against the authoring contract and registered through the
    declaration `vqapr new sample` writes (record `172`), so this covers the seam between them:
    the loader adapts an authoring model rather than refusing it.
    """
    root = tmp_path / "proj"
    root.mkdir()
    panel = journey.install(root)
    result = journey.execute(root, panel)

    # One callback and one due item per session (record `148`): the standalone valuation
    # occurrences the journey used to dispatch are gone, because the book is valued at the
    # instant it fills. 734 sessions since record `167` left the first one out of the horizon,
    # so that the first decision has a published close behind it and `vqapr check` accepts
    # what `install` registered.
    assert result.occurrences == 1468
    # The Account is what the economics live in, and valuing the book at a fill does not add a
    # commit of its own: a mark values the book, it does not trade it. Unchanged by the shorter
    # horizon: the strategy Held through the first session either way.
    assert result.account_version == 729
    # The run state advances on every publication. It stood at 3664 with the valuation clock;
    # the standalone valuation publications are gone, and the NAV each fill measures now
    # rides the mark transition instead of a publication of its own. The dropped session took
    # its callback publication and its held valuation with it (2929 before record `167`).
    assert result.run_state_version == 2927


@pytest.mark.slow
def test_the_installed_sample_is_accepted_by_the_products_own_check(tmp_path: Path) -> None:
    """What `install` registers passes the judgments every door asks before the freeze.

    The 0.6.0 call-flow review (record `167`) ran the installed sample through the CLI and was
    refused with `check.lookback.uncovered`: the horizon opened on the first session, whose close
    is published at 15:30, after the 08:00 decision, while `execute` reached the freeze without
    asking. The horizon moved (record `167`) and the judgments moved into `preflight_run`
    (record `168`), so this asks the public door the journey itself uses.
    """
    from vqapr.public import Workspace, preflight_run

    root = tmp_path / "proj"
    root.mkdir()
    journey.install(root)
    workspace = Workspace.open(root)
    frozen = preflight_run(workspace, workspace.run_definition(journey.RUN_ID))
    assert frozen.run_id == journey.RUN_ID
