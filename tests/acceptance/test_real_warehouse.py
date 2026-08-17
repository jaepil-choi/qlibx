"""Acceptance coverage that runs on real KRX market data, never on invented values.

The committed excerpt under ``tests/fixtures/real`` is a verbatim slice of the vendor warehouse
produced by ``scripts/extract_dw_fixture.py``. These tests always run against it. When the full
local warehouse is present they additionally regenerate the slice and assert the committed rows
still match it, so the fixture cannot silently drift away from reality.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, time
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

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "real"
WAREHOUSE = REPO_ROOT / "data" / "DW"
VENUE = "Asia/Seoul"
OFFSET = "+09:00"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observation_path(manifest: dict[str, object]) -> Path:
    return FIXTURE / str(manifest["observation_path"])


@pytest.fixture(scope="module")
def execution_path(manifest: dict[str, object]) -> Path:
    return FIXTURE / str(manifest["execution_path"])


@pytest.fixture(scope="module")
def instruments(manifest: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(row["ticker"]) for row in manifest["universe"])


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


def _rows(path: Path, order: str) -> list[tuple[object, ...]]:
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY {order}"
        ).fetchall()
    finally:
        con.close()


def _sessions(path: Path) -> list[date]:
    con = duckdb.connect()
    try:
        return [
            row[0]
            for row in con.execute(
                f"""
                SELECT DISTINCT CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session
                FROM read_parquet('{path.as_posix()}')
                ORDER BY session
                """
            ).fetchall()
        ]
    finally:
        con.close()


def _instant(day: date, at: time) -> datetime:
    return LocalInstantDeclaration(day, at, VENUE, 0, OFFSET).instant


def test_committed_fixture_carries_only_genuine_sessions(
    manifest: dict[str, object], observation_path: Path
) -> None:
    assert manifest["rows"] == 88
    assert manifest["sessions"] == 22
    assert manifest["halted_rows"] == 0

    con = duckdb.connect()
    try:
        table = f"read_parquet('{observation_path.as_posix()}')"
        assert con.execute(f"SELECT count(*) FROM {table} WHERE close <= 0").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == manifest["rows"]
        weekend = con.execute(
            f"""
            SELECT count(*) FROM {table}
            WHERE dayofweek(available_at AT TIME ZONE '{VENUE}') IN (0, 6)
            """
        ).fetchone()[0]
    finally:
        con.close()
    assert weekend == 0, "real KRX sessions never fall on a weekend"


@pytest.mark.skipif(
    not (WAREHOUSE / "fng_stock_daily_prices.csv").is_file(),
    reason="full data/DW warehouse is absent; committed excerpt is still exercised above",
)
def test_committed_fixture_still_matches_the_warehouse(
    tmp_path: Path,
    manifest: dict[str, object],
    observation_path: Path,
    execution_path: Path,
) -> None:
    from extract_dw_fixture import FixtureSpec, extract

    spec = manifest["spec"]
    regenerated = extract(
        FixtureSpec(
            asof=str(spec["asof"]),
            start=str(spec["start"]),
            end=str(spec["end"]),
            universe_size=int(spec["universe_size"]),
        ),
        tmp_path,
    )

    assert regenerated["universe"] == manifest["universe"]
    assert regenerated["rows"] == manifest["rows"]
    assert regenerated["sessions"] == manifest["sessions"]
    assert _rows(tmp_path / str(regenerated["observation_path"]), "1, 2") == _rows(
        observation_path, "1, 2"
    )
    assert _rows(tmp_path / str(regenerated["execution_path"]), "1, 2") == _rows(
        execution_path, "1, 2"
    )


def test_real_observations_stay_point_in_time(
    observation_path: Path, instruments: tuple[str, ...]
) -> None:
    """A cutoff before the venue close must not expose that session's own close."""
    registration = DatasetRegistration.of(
        "price_daily",
        "krx-observation",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    )
    source = SourceSpec.of("krx-observation", observation_path)
    requirement = DataRequirement.of(
        "probe", "price_daily", fields=("close",), lookback=RowsLookback(1)
    )
    cutoff_session = _sessions(observation_path)[3]
    morning = _instant(cutoff_session, time(8, 30))

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
        assert isinstance(row["close"], Decimal)
    assert batch.access.source_id == "krx-observation"
    assert len(batch.access.source_digest) == 64


def test_real_execution_snapshot_selects_the_exact_close(
    observation_path: Path, execution_path: Path, instruments: tuple[str, ...]
) -> None:
    registration = ExecutionInputRegistration.of(
        "krx-daily",
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", execution_path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(FillSelector.SAME_DAY, time(15, 30), VENUE, "close"),
    )
    sessions = _sessions(observation_path)
    decision_session = sessions[3]
    decision = _instant(decision_session, time(8, 30))
    horizon = _instant(sessions[-1], time(23, 0))

    target = registration.fill.select_target(registration, decision_time=decision, end_time=horizon)
    assert target is not None
    assert target.target_at > decision
    assert target.target_at.astimezone(decision.tzinfo).date() == decision_session

    snapshot = exact_execution_snapshot(
        registration.table,
        target_at=target.target_at,
        target_instruments=instruments,
        held_instruments=(),
        trade_price="close",
    )
    assert snapshot.duplicate_instruments == ()
    assert snapshot.missing_target_instruments == ()
    assert len(snapshot.rows) == len(instruments)
    for row in snapshot.rows:
        assert row.is_tradable is True
        assert isinstance(row.price, Decimal)
        assert row.price > 0


def test_real_close_is_visible_exactly_at_the_venue_close(
    observation_path: Path, instruments: tuple[str, ...]
) -> None:
    """Marking at the execution cutoff must see that session's own close, not a stale one."""
    registration = DatasetRegistration.of(
        "price_daily",
        "krx-observation",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    )
    source = SourceSpec.of("krx-observation", observation_path)
    requirement = DataRequirement.of(
        "mark", "price_daily", fields=("close",), lookback=RowsLookback(1)
    )
    session = _sessions(observation_path)[3]
    cutoff = _instant(session, time(15, 30))

    window = ModelWindow(
        evaluation_time=cutoff,
        instruments=instruments,
        store=DuckDbObservationStore(_Catalog(registration, source)),
        allowed_requirements=(requirement,),
    )
    batch = window.observations(requirement)

    assert len(batch.rows) == len(instruments)
    for row in batch.rows:
        assert row["available_at"] == cutoff
