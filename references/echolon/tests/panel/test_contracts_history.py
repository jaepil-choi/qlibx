"""PanelView.contracts_history full-curve and no-lookahead falsifiers."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from echolon.panel.models import PanelManifest
from echolon.panel.snapshot import CONTRACT_COLUMNS, PanelData, PanelView


def _panel_with_contracts(
    contract_rows: dict[str, list[dict[str, object]]],
) -> PanelData:
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=index) for index in range(4)]
    contracts = {
        instrument: pd.DataFrame(
            rows,
            index=[dates[index // 3] for index in range(len(rows))],
        )
        for instrument, rows in contract_rows.items()
    }
    manifest = PanelManifest(
        schema="panel/v1",
        version="test_snapshot",
        created_at="2024-01-02T00:00:00+00:00",
        source_refs=["test"],
        calendar_start=dates[0],
        calendar_end=dates[-1],
        instruments=["cu"],
        files={},
        qc_report="qc_report.json",
        qc_status="PASS",
    )
    return PanelData(
        snapshot_dir=None,
        manifest=manifest,
        bars={},
        curves={},
        contracts=contracts,
        meta={},
    )


def _contract_row(contract: str, settle: float) -> dict[str, object]:
    return {
        "symbol": contract.upper(),
        "open": settle,
        "high": settle,
        "low": settle,
        "close": settle,
        "settle": settle,
        "volume": 100,
        "open_interest": 200.0,
        "contract": contract.upper(),
    }


def test_contracts_history_is_no_lookahead_and_tails_by_unique_date() -> None:
    rows = [
        _contract_row(f"cu24{month:02d}", 100.0 + day * 10 + month)
        for day in range(4)
        for month in range(1, 4)
    ]
    panel = _panel_with_contracts({"cu": rows})
    view = PanelView(panel, dt.date(2024, 1, 4))

    history = view.contracts_history("CU", 2)

    assert list(history.columns) == CONTRACT_COLUMNS
    assert history.index.unique().tolist() == [
        dt.date(2024, 1, 3),
        dt.date(2024, 1, 4),
    ]
    assert history.groupby(level=0).size().tolist() == [3, 3]
    assert history.index.max() <= view.date
    assert dt.date(2024, 1, 5) not in history.index


def test_contracts_history_short_history_returns_every_visible_date() -> None:
    rows = [_contract_row(f"cu24{month:02d}", 100.0 + month) for month in range(1, 4)]
    panel = _panel_with_contracts({"cu": rows})
    view = PanelView(panel, dt.date(2024, 1, 2))

    history = view.contracts_history("cu", 20)

    assert history.index.unique().tolist() == [dt.date(2024, 1, 2)]
    assert len(history) == 3


def test_contracts_history_missing_instrument_returns_canonical_empty_frame() -> None:
    panel = _panel_with_contracts({})
    view = PanelView(panel, dt.date(2024, 1, 2))

    history = view.contracts_history("cu", 5)

    assert history.empty
    assert list(history.columns) == CONTRACT_COLUMNS


@pytest.mark.parametrize("lookback", [0, -1])
def test_contracts_history_rejects_non_positive_lookback(lookback: int) -> None:
    panel = _panel_with_contracts({"cu": [_contract_row("cu2401", 100.0)]})
    view = PanelView(panel, dt.date(2024, 1, 2))

    with pytest.raises(ValueError, match="lookback must be positive"):
        view.contracts_history("cu", lookback)


def test_contracts_history_real_p2_v4_mid_2020_full_curve(p2_v4_panel: Path) -> None:
    panel = PanelData.load(p2_v4_panel)
    view_date = dt.date(2020, 6, 15)

    history = panel.view(view_date).contracts_history("cu", 5)
    latest = history.loc[[history.index.max()]]

    assert history.index.max() <= view_date
    assert latest["contract"].nunique() > 1

