"""Acceptance coverage that runs on the real KRX warehouse, never on invented values.

The fixture is a small deterministic slice of ``data/DW`` produced by
``scripts/extract_dw_fixture.py``. When the local warehouse is absent the module skips with an
explicit reason: this suite is only meaningful against real inputs.
"""

from __future__ import annotations

import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    exact_execution_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

WAREHOUSE = REPO_ROOT / "data" / "DW"
VENUE = "Asia/Seoul"

pytestmark = pytest.mark.skipif(
    not (WAREHOUSE / "fng_stock_daily_prices.csv").is_file(),
    reason="real warehouse data/DW is required; run scripts/extract_dw_fixture.py inputs first",
)


@pytest.fixture(scope="module")
def warehouse_slice(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    from extract_dw_fixture import FixtureSpec, extract

    out = tmp_path_factory.mktemp("dw-fixture")
    spec = FixtureSpec(asof="20260331", start="20260401", end="20260430", universe_size=4)
    manifest = extract(spec, out)
    manifest["dir"] = out
    return manifest


class _Catalog:
    def __init__(self, registration: DatasetRegistration, source: SourceSpec) -> None:
        self._registration = registration
        self._source = source

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        assert raw_dataset_id == str(self._registration.dataset_id)
        return self._registration

    def source(self, raw_source_id: str) -> SourceSpec:
        assert raw_source_id == str(self._source.source_id)
        return self._source


def test_real_slice_has_only_genuine_sessions_and_prices(warehouse_slice) -> None:
    assert warehouse_slice["rows"] > 0
    assert warehouse_slice["sessions"] > 5
    assert warehouse_slice["halted_rows"] == 0

    path = Path(warehouse_slice["dir"]) / str(warehouse_slice["observation_path"])
    con = duckdb.connect()
    try:
        negative = con.execute(
            f"SELECT count(*) FROM read_parquet('{path.as_posix()}') WHERE close <= 0"
        ).fetchone()[0]
        weekend = con.execute(
            f"""
            SELECT count(*) FROM read_parquet('{path.as_posix()}')
            WHERE dayofweek(available_at AT TIME ZONE '{VENUE}') IN (0, 6)
            """
        ).fetchone()[0]
    finally:
        con.close()
    assert negative == 0
    assert weekend == 0, "real KRX sessions never fall on a weekend"


def test_real_observations_stay_point_in_time(warehouse_slice) -> None:
    """A window cutoff before the venue close must not expose that session's own close."""
    path = Path(warehouse_slice["dir"]) / str(warehouse_slice["observation_path"])
    registration = DatasetRegistration.of(
        "price_daily",
        "krx-observation",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    )
    source = SourceSpec.of("krx-observation", path)
    instruments = tuple(str(row["ticker"]) for row in warehouse_slice["universe"])
    requirement = DataRequirement.of(
        "probe", "price_daily", fields=("close",), lookback=RowsLookback(1)
    )

    sessions = _sessions(path)
    cutoff_session = sessions[3]
    morning = LocalInstantDeclaration(cutoff_session, time(8, 30), VENUE, 0, "+09:00").instant

    window = ModelWindow(
        evaluation_time=morning,
        instruments=instruments,
        store=DuckDbObservationStore(_Catalog(registration, source)),
        allowed_requirements=(requirement,),
    )
    batch = window.observations(requirement)

    assert batch.rows, "the probe must actually read real rows"
    for row in batch.rows:
        assert row["available_at"] < morning
        assert row["available_at"].astimezone(morning.tzinfo).date() < cutoff_session
    assert batch.access.source_digest, "actual-read lineage must carry the physical digest"


def test_real_execution_snapshot_selects_the_exact_close(warehouse_slice) -> None:
    path = Path(warehouse_slice["dir"]) / str(warehouse_slice["execution_path"])
    registration = ExecutionInputRegistration.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(FillSelector.SAME_DAY, time(15, 30), VENUE, "close"),
    )
    sessions = _sessions(Path(warehouse_slice["dir"]) / str(warehouse_slice["observation_path"]))
    decision_session = sessions[3]
    decision = LocalInstantDeclaration(decision_session, time(8, 30), VENUE, 0, "+09:00").instant
    horizon = LocalInstantDeclaration(sessions[-1], time(23, 0), VENUE, 0, "+09:00").instant

    target = registration.fill.select_target(registration, decision_time=decision, end_time=horizon)
    assert target is not None
    assert target.target_at > decision
    assert target.target_at.astimezone(decision.tzinfo).date() == decision_session

    instruments = tuple(str(row["ticker"]) for row in warehouse_slice["universe"])
    snapshot = exact_execution_snapshot(
        registration.table,
        target_at=target.target_at,
        target_instruments=instruments,
        held_instruments=(),
        trade_price="close",
    )
    assert snapshot.duplicate_instruments == ()
    assert snapshot.missing_target_instruments == ()
    for row in snapshot.rows:
        assert row.is_tradable is True
        assert isinstance(row.price, Decimal)
        assert row.price > 0


def _sessions(observation_path: Path) -> list[date]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session
            FROM read_parquet('{observation_path.as_posix()}')
            ORDER BY session
            """
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]
