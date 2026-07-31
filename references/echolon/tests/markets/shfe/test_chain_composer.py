"""
Tests for the chain_composer (Gate 1C WS2 B2.1).

Real SHFE market data is not available on this dev machine, so all
tests are SYNTHETIC: we fabricate ``sort_by_contract/{contract}.csv``
files with the canonical column schema and exercise the chain assembly
logic.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from echolon.data.loaders.chain_composer import (
    get_contract_chain,
    get_curve_snapshot,
)
from echolon.markets.shfe.adapter import SHFEAdapter


# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------


def _write_contract_csv(
    market_data_dir: Path,
    asset: str,
    contract: str,
    dates: list[date],
    close_base: float,
    settlement_offset: float = 1.5,
):
    """Fabricate a per-contract OHLCV csv at the canonical layout."""
    target = market_data_dir / "SHFE" / asset / "sort_by_contract"
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, d in enumerate(dates):
        close = close_base + i
        rows.append({
            "date": d.isoformat(),
            "contract": contract,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            # Settlement deliberately != close so tests can prove
            # carry indicators consume the right column.
            "settlement": close + settlement_offset,
            "volume": 1000 + i,
            "open_interest": 5000 + i,
        })
    pd.DataFrame(rows).to_csv(target / f"{contract}.csv", index=False)


def _build_zinc_curve_fixture(tmp_path: Path, snapshot_date: date) -> Path:
    """Create 4 zinc contracts active on ``snapshot_date``.

    Returns ``market_data_dir`` rooted at ``tmp_path``.
    """
    # All 4 contracts have a row for snapshot_date. Expiries are
    # spread monotonically so chain ordering by expiry is unambiguous.
    contracts = ["zn2407", "zn2408", "zn2409", "zn2410"]
    bases = [22000.0, 22050.0, 22080.0, 22100.0]
    for contract, base in zip(contracts, bases):
        _write_contract_csv(
            tmp_path, "zinc", contract,
            dates=[snapshot_date],
            close_base=base,
        )
    return tmp_path


# ---------------------------------------------------------------------------
# get_contract_chain
# ---------------------------------------------------------------------------


def test_get_contract_chain_returns_active_contracts_sorted_by_expiry(tmp_path):
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)

    chain = get_contract_chain(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    # Expiry ascending → 2407 (June expiry) first.
    assert chain == ["zn2407", "zn2408", "zn2409", "zn2410"]
    assert len(chain) >= 3, "Audit doc says spec requires ≥ 3 active contracts"


def test_get_contract_chain_excludes_expired(tmp_path):
    snapshot_date = date(2024, 8, 15)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    # zn2407 expires 2024-06-30 → before snapshot_date → must be excluded.
    chain = get_contract_chain(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    assert "zn2407" not in chain
    # zn2408 expires 2024-07-31 → before snapshot_date → also excluded.
    assert "zn2408" not in chain
    # zn2409 expires 2024-08-31 → on or after snapshot_date → present.
    assert "zn2409" in chain


def test_get_contract_chain_excludes_contracts_without_date_row(tmp_path):
    """A contract whose CSV exists but has no row for the snapshot date
    must NOT appear in the chain."""
    target_date = date(2024, 6, 5)
    other_date = date(2024, 5, 15)

    _write_contract_csv(tmp_path, "zinc", "zn2407",
                        dates=[target_date], close_base=22000.0)
    _write_contract_csv(tmp_path, "zinc", "zn2408",
                        dates=[target_date], close_base=22050.0)
    # zn2409 has data only for an OTHER date → must be excluded.
    _write_contract_csv(tmp_path, "zinc", "zn2409",
                        dates=[other_date], close_base=22080.0)

    chain = get_contract_chain(
        "zn",
        target_date,
        market="SHFE",
        market_data_dir=tmp_path,
    )
    assert "zn2407" in chain
    assert "zn2408" in chain
    assert "zn2409" not in chain


def test_get_contract_chain_n_contracts_truncates(tmp_path):
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    chain = get_contract_chain(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
        n_contracts=2,
    )
    assert chain == ["zn2407", "zn2408"]


def test_get_contract_chain_unknown_symbol_raises(tmp_path):
    from echolon.errors import DataError
    with pytest.raises(DataError):
        get_contract_chain(
            "nosuchproduct",
            date(2024, 6, 5),
            market="SHFE",
            market_data_dir=tmp_path,
        )


def test_get_contract_chain_accepts_full_name(tmp_path):
    """Both 'zn' (code) and 'zinc' (name) should resolve."""
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    chain_code = get_contract_chain(
        "zn", snapshot_date, market="SHFE", market_data_dir=market_data_dir,
    )
    chain_name = get_contract_chain(
        "zinc", snapshot_date, market="SHFE", market_data_dir=market_data_dir,
    )
    assert chain_code == chain_name


# ---------------------------------------------------------------------------
# get_curve_snapshot
# ---------------------------------------------------------------------------


def test_get_curve_snapshot_row_per_active_contract(tmp_path):
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    snap = get_curve_snapshot(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    assert len(snap) == 4
    # Expected columns per chain_composer docstring.
    for col in (
        "contract", "date", "expiry_date", "days_to_expiry",
        "open", "high", "low", "close", "volume", "settlement",
    ):
        assert col in snap.columns, f"missing column {col}"
    # Sorted by expiry ascending → front first.
    assert snap.iloc[0]["contract"] == "zn2407"
    assert snap.iloc[-1]["contract"] == "zn2410"


def test_get_curve_snapshot_settlement_populated_and_distinct_from_close(tmp_path):
    """Settlement column must be present AND non-equal to close — proves
    the snapshot reads the right column (Q50 spike load-bearing claim)."""
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    snap = get_curve_snapshot(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    # Per the synthetic fixture, settlement = close + 1.5 on every row.
    assert (snap["settlement"] - snap["close"]).round(2).eq(1.5).all()


def test_get_curve_snapshot_days_to_expiry_monotone(tmp_path):
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    snap = get_curve_snapshot(
        "zn",
        snapshot_date,
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    dtes = snap["days_to_expiry"].tolist()
    assert dtes == sorted(dtes)
    assert all(d >= 0 for d in dtes)


def test_get_curve_snapshot_empty_when_no_active(tmp_path):
    """Far-future date with no active contracts returns empty DataFrame
    with the canonical columns."""
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    snap = get_curve_snapshot(
        "zn",
        date(2099, 1, 1),
        market="SHFE",
        market_data_dir=market_data_dir,
    )
    assert len(snap) == 0
    assert "settlement" in snap.columns


# ---------------------------------------------------------------------------
# SHFEAdapter wrappers
# ---------------------------------------------------------------------------


def test_shfe_adapter_get_contract_chain_delegates(tmp_path):
    """SHFEAdapter.get_contract_chain delegates to chain_composer using
    its market_data_dir."""
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    adapter = SHFEAdapter(symbol="zn", market_data_dir=market_data_dir)
    chain = adapter.get_contract_chain(snapshot_date)
    assert chain == ["zn2407", "zn2408", "zn2409", "zn2410"]


def test_shfe_adapter_get_curve_snapshot_delegates(tmp_path):
    snapshot_date = date(2024, 6, 5)
    market_data_dir = _build_zinc_curve_fixture(tmp_path, snapshot_date)
    adapter = SHFEAdapter(symbol="zn", market_data_dir=market_data_dir)
    snap = adapter.get_curve_snapshot(snapshot_date, n_contracts=3)
    assert len(snap) == 3
    assert list(snap["contract"]) == ["zn2407", "zn2408", "zn2409"]
