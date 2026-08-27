"""The sample panel is deliberately unbalanced, and that shape is the thing under test.

A balanced panel would let a Strategy look correct while assuming every instrument exists on every
session. These tests pin the two cases that break that assumption and the fact that the Strategy
resolves neither of them itself.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from vqapr.agent.sample.build import (
    DEAD_SESSIONS,
    LATE_SESSIONS,
    WAREHOUSE,
    WIND_DOWN_SESSIONS,
    build,
)
from vqapr.agent.sample.reversal_5d import LOOKBACK, SampleReversal5d

pytestmark = pytest.mark.real_data

_MISSING = not WAREHOUSE.exists()
_REASON = f"warehouse {WAREHOUSE} is not provisioned"


@pytest.fixture(scope="module")
def panel(tmp_path_factory: pytest.TempPathFactory):
    if _MISSING:
        pytest.skip(_REASON)
    return build(tmp_path_factory.mktemp("sample"))


def _rows(path: Path, instrument: str, field: str) -> list:
    return sorted(
        row[field] for row in pq.read_table(path).to_pylist() if row["instrument"] == instrument
    )


def test_the_panel_holds_ten_named_instruments(panel) -> None:
    assert len(panel.instruments) == 10
    assert len(set(panel.instruments)) == 10


def test_one_instrument_lists_after_the_window_opens(panel) -> None:
    """A late lister has no rows at the start, which is what removes it from early sessions."""
    observed = _rows(panel.observations, panel.late_listed, "available_at")
    assert len(observed) == len(panel.sessions) - LATE_SESSIONS
    assert observed[-1] == max(
        row["available_at"] for row in pq.read_table(panel.observations).to_pylist()
    )


def test_one_instrument_stops_before_the_window_closes(panel) -> None:
    observed = _rows(panel.observations, panel.delisted, "available_at")
    assert len(observed) == len(panel.sessions) - DEAD_SESSIONS


def test_the_delisted_name_keeps_a_tradable_tail(panel) -> None:
    """A position is closed after the Strategy drops the name, and that fill needs a price."""
    observed = _rows(panel.observations, panel.delisted, "available_at")
    tradable = _rows(panel.execution, panel.delisted, "trade_at")
    assert len(tradable) == len(observed) + WIND_DOWN_SESSIONS
    assert max(tradable) > max(observed)


def test_prices_are_exact(panel) -> None:
    """Row scalars keep their source type, so a float source would make the callback inexact."""
    row = pq.read_table(panel.observations).to_pylist()[0]
    assert isinstance(row["close"], Decimal)


def test_the_strategy_declares_the_lookback_it_reads(panel) -> None:
    declared = SampleReversal5d().inputs()["prices"]
    assert declared.lookback.rows == LOOKBACK
    assert LOOKBACK == 6, "a five-day return compares six observations"


def test_the_strategy_never_inspects_listing_status() -> None:
    """Tradability is an execution-time fact; a callback that asks about it is guessing."""
    source = Path(SampleReversal5d.__module__.replace(".", "/")).with_suffix(".py")
    text = (Path("src") / source).read_text(encoding="utf-8")
    body = text.split("def decide", 1)[1]
    for forbidden in ("is_tradable", "listed", "delist", "halt", "max_available_at"):
        assert forbidden not in body


def test_the_sample_journey_runs_end_to_end(tmp_path: Path) -> None:
    """The reference journey an agent copies must actually run.

    `reversal_5d` is written against the authoring contract while `journey` registers it
    through the legacy component path, so this covers the seam between them: the loader
    adapts an authoring model rather than refusing it. Without that adaptation the
    registration fails with `component.load.wrong_type`, and the reference an agent is
    told to copy does not work.
    """
    from vqapr.agent.sample import journey

    root = tmp_path / "proj"
    root.mkdir()
    panel = journey.install(root)
    result = journey.execute(root, panel)

    # The numbers the journey produced before the migration, unchanged.
    assert result.occurrences == 2940
    # The Account is what the economics live in, and an independent valuation clock must not
    # touch it: a mark taken without a fill values the book, it does not trade it.
    assert result.account_version == 729
    # The run state advances on every publication, so it also counts the marks a valuation
    # records without trading. It is pinned separately precisely because it is the counter the
    # valuation clock is allowed to move.
    assert result.run_state_version == 3664
