"""As-of Shenwan sector resolution falsifiers."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta, PanelManifest
from echolon.panel.sector import resolve_sector_asof
from echolon.panel.snapshot import PanelData


def _panel(membership: pd.DataFrame | None) -> PanelData:
    dates = [dt.date(2018, 6, 30), dt.date(2020, 6, 30)]
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.0],
            "high": [10.0, 10.0],
            "low": [10.0, 10.0],
            "close": [10.0, 10.0],
            "settle": [10.0, 10.0],
            "volume": [1.0, 1.0],
            "open_interest": [0.0, 0.0],
            "contract": ["000001.sz", "000001.sz"],
        },
        index=dates,
    )
    return PanelData(
        snapshot_dir=None,
        manifest=PanelManifest(
            version="sector-test",
            created_at="2026-07-13T00:00:00+00:00",
            source_refs=["synthetic"],
            calendar_start=dates[0],
            calendar_end=dates[-1],
            instruments=["000001.sz"],
            qc_report="qc_report.json",
            qc_status="PASS",
        ),
        bars={"000001.sz": bars},
        curves={},
        contracts={},
        meta={
            "000001.sz": InstrumentMeta(
                instrument_id="000001.sz",
                sector="META-FALLBACK",
                multiplier=1.0,
                tick=0.01,
                margin_rate=1.0,
                commission=0.0,
                commission_type="percentage",
            )
        },
        sector_membership=membership,
    )


def test_reclassified_name_uses_old_sector_before_new_in_date() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz", "000001.sz"],
            "l1_code": ["801010", "801780"],
            "in_date": ["20100101", "20190701"],
            "out_date": ["20190630", None],
        }
    )

    assert (
        resolve_sector_asof(
            membership, "000001.SZ", dt.date(2018, 6, 30)
        )
        == "801010"
    )
    assert (
        resolve_sector_asof(
            membership, "000001.sz", dt.date(2020, 6, 30)
        )
        == "801780"
    )


def test_csv_integer_dates_keep_old_sector_before_reclassification(
    tmp_path: Path,
) -> None:
    membership_path = tmp_path / "sw_membership.csv"
    pd.DataFrame(
        {
            "instrument": ["000001.sz", "000001.sz"],
            "l1_code": ["OLD", "NEW"],
            "in_date": [20100101, 20190701],
            "out_date": [20190630, None],
        }
    ).to_csv(membership_path, index=False)

    membership = pd.read_csv(membership_path)

    assert membership["in_date"].dtype.kind in "iu"
    assert membership["out_date"].dtype.kind == "f"
    assert resolve_sector_asof(membership, "000001.sz", "20180630") == "OLD"
    assert resolve_sector_asof(membership, "000001.sz", "20200630") == "NEW"


def test_missing_asof_membership_uses_explicit_fallback_only() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz"],
            "l1_code": ["801780"],
            "in_date": ["20190701"],
            "out_date": [None],
        }
    )

    assert resolve_sector_asof(membership, "000001.sz", "2018-06-30") is None
    assert (
        resolve_sector_asof(
            membership, "000001.sz", "2018-06-30", fallback="UNKNOWN"
        )
        == "UNKNOWN"
    )


def test_nonempty_malformed_membership_date_is_not_coerced_to_nat() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz"],
            "l1_code": ["801780"],
            "in_date": ["not-a-date"],
            "out_date": [None],
        }
    )

    with pytest.raises(ValueError, match="invalid non-empty in_date"):
        resolve_sector_asof(membership, "000001.sz", "20200630")


def test_panel_view_sector_asof_switches_on_reclassification_date() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz", "000001.sz"],
            "l1_code": ["OLD", "NEW"],
            "in_date": ["20100101", "20190701"],
            "out_date": ["20190630", None],
        }
    )
    panel = _panel(membership)

    assert panel.view("2018-06-30").sector_asof("000001.sz") == "OLD"
    assert panel.view("2020-06-30").sector_asof("000001.sz") == "NEW"


def test_panel_view_name_absent_from_membership_uses_meta_sector() -> None:
    membership = pd.DataFrame(
        columns=["instrument", "l1_code", "in_date", "out_date"]
    )

    assert _panel(membership).view("2020-06-30").sector_asof("000001.sz") == "META-FALLBACK"


def test_futures_panel_without_membership_uses_meta_sector() -> None:
    assert _panel(None).view("2020-06-30").sector_asof("000001.sz") == "META-FALLBACK"
