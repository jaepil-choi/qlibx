"""The one door (`data/validation.py`, record `234`): measured once, verified by identity after.

`verify_source` is what registration runs, and what it hands back carries the digest of the
bytes it measured and, for an execution-role table, the prices that are positive on every
tradable row. `require_verified` is the check every later reader makes: no scan, one digest.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data import validation
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.project.store import Workspace
from vqapr.public import register_dataset

KST = ZoneInfo("Asia/Seoul")
KERNELS = ("describe", "describe_projection", "key_check", "span_check", "finite_check")


def _write(path: Path, rows: str) -> Path:
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _prices(tmp_path: Path, *, close_b: str = "50.0") -> Path:
    return _write(
        tmp_path / "prices.parquet",
        f"""
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', {close_b}::DOUBLE),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 101.0::DOUBLE)
        ) AS t(available_at, instrument, close)
        """,
    )


def _registration() -> DatasetRegistration:
    return DatasetRegistration.of(
        "price_daily",
        "prices",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
        grain="instrument_instant",
    )


def test_verify_source_measures_the_digest_and_registration_keeps_it(tmp_path: Path) -> None:
    parquet = _prices(tmp_path)

    diagnosis, _, measured = validation.verify_source(
        _registration(), SourceSpec.of("prices", parquet)
    )

    assert diagnosis.ok
    assert measured.verified and measured.source_digest is not None
    assert len(measured.source_digest) == 64
    assert measured.span == (
        datetime(2024, 3, 5, 15, 30, tzinfo=KST),
        datetime(2024, 3, 6, 15, 30, tzinfo=KST),
    )
    assert measured.execution_prices is None, "no execution role, no price facts"

    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))
    stored = Workspace.open(tmp_path).dataset("price_daily")
    assert stored.source_digest == measured.source_digest, "the workspace document keeps it"


def test_a_verified_read_hashes_once_and_scans_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet = _prices(tmp_path)
    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))
    scans: list[str] = []
    for name in KERNELS:
        original = getattr(validation.scan, name)

        def counting(*args, _name=name, _original=original, **kwargs):
            scans.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(validation.scan, name, counting)
    hashes: list[Path] = []
    original_digest = validation.physical_digest

    def counting_digest(path: Path) -> str:
        hashes.append(path)
        return original_digest(path)

    monkeypatch.setattr(validation, "physical_digest", counting_digest)
    # `Workspace.source_digest` hashes through its own import; count it the same way.
    from vqapr.project import store as store_module

    monkeypatch.setattr(store_module, "physical_digest", counting_digest)

    workspace = Workspace.open(tmp_path)
    first = workspace.require_verified("price_daily")
    second = workspace.require_verified("price_daily")
    workspace.source_digest(workspace.source("prices"))

    assert first.verified and second.source_digest == first.source_digest
    assert scans == [], "verifying a registered source scans nothing"
    assert len(hashes) == 1, "one workspace object hashes a source once, however often it is asked"


def test_a_changed_file_is_refused_by_name(tmp_path: Path) -> None:
    parquet = _prices(tmp_path)
    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))
    _prices(tmp_path, close_b="51.0")  # the same path, other bytes

    with pytest.raises(VqaprError) as refused:
        Workspace.open(tmp_path).require_verified("price_daily")

    failure = refused.value.failures[0]
    assert failure.code == "dataset.source_changed"
    assert "register dataset 'price_daily' again" in str(failure.fix)


def test_registering_again_after_the_file_changed_replaces_the_measurement(tmp_path: Path) -> None:
    """The fix `dataset.source_changed` names is possible: the same declaration on the bytes as
    they are now replaces the measured half (span, digest, price facts) under the same id."""
    parquet = _prices(tmp_path)
    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))
    before = Workspace.open(tmp_path).dataset("price_daily").source_digest
    _prices(tmp_path, close_b="51.0")

    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))

    after = Workspace.open(tmp_path).require_verified("price_daily")
    assert after.verified and after.source_digest != before


def test_a_declaration_that_changed_is_still_refused_when_registered_again(tmp_path: Path) -> None:
    parquet = _prices(tmp_path)
    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))
    renamed = DatasetRegistration.of(
        "price_daily",
        "prices",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"px": "close"},
        field_types={"px": "DOUBLE"},
        grain="instrument_instant",
    )

    with pytest.raises(VqaprError) as refused:
        register_dataset(tmp_path, renamed, SourceSpec.of("prices", parquet))

    assert refused.value.failures[0].code == "dataset.registered"


def test_a_document_written_before_the_digest_is_repaired_by_registering_again(
    tmp_path: Path,
) -> None:
    parquet = _prices(tmp_path)
    unmeasured = _registration().with_span(
        datetime(2024, 3, 5, 15, 30, tzinfo=KST), datetime(2024, 3, 6, 15, 30, tzinfo=KST)
    )
    with Workspace.transaction(Workspace.create(tmp_path)) as t:
        t.register_dataset(unmeasured, SourceSpec.of("prices", parquet))
    with pytest.raises(VqaprError) as refused:
        Workspace.open(tmp_path).require_verified("price_daily")
    assert refused.value.failures[0].code == "dataset.unverified"

    register_dataset(tmp_path, _registration(), SourceSpec.of("prices", parquet))

    assert Workspace.open(tmp_path).require_verified("price_daily").verified


def test_a_registration_without_a_measurement_is_refused_by_name(tmp_path: Path) -> None:
    """A document written before record `234` carries no digest; it opens and lists, and a run
    that reads it is told to register it again -- the quarantine `grain` and `field_types` had."""
    parquet = _prices(tmp_path)
    registration = _registration().with_span(
        datetime(2024, 3, 5, 15, 30, tzinfo=KST), datetime(2024, 3, 6, 15, 30, tzinfo=KST)
    )
    assert not registration.verified

    with pytest.raises(VqaprError) as refused:
        validation.require_verified(registration, SourceSpec.of("prices", parquet))

    assert refused.value.failures[0].code == "dataset.unverified"
    assert "`vqapr register <its declaration file>`" in str(refused.value.failures[0].fix)


def test_a_run_published_registration_is_told_to_publish_again(tmp_path: Path) -> None:
    """A dataset a run published has no declaration file to hand `register`; the one command that
    measures it again is the run, told to replace what it published. The refusal names that
    command and the run, for both the missing measurement and a file changed since
    (`docs/issues/report-2026-09-10-unverified-fix-names-no-command-for-a-run-published-dataset`)."""
    parquet = _prices(tmp_path)
    spec = SourceSpec.of("prices", parquet)
    published = (
        _registration()
        .with_span(
            datetime(2024, 3, 5, 15, 30, tzinfo=KST), datetime(2024, 3, 6, 15, 30, tzinfo=KST)
        )
        .with_producer("alpha-001", "alpha@deadbeef")
    )

    with pytest.raises(VqaprError) as unverified:
        validation.require_verified(published, spec)
    failure = unverified.value.failures[0]
    assert failure.code == "dataset.unverified"
    assert "published by run 'alpha-001'" in str(failure.observed)
    assert "`vqapr run alpha-001 --force`" in str(failure.fix)
    assert "register" not in str(failure.fix)
    assert "`vqapr run alpha-001 --force`" in str(unverified.value.retry_precondition)

    with pytest.raises(VqaprError) as changed:
        validation.require_verified(
            published.with_verification("0" * 64, None), spec, digest="1" * 64
        )
    assert changed.value.failures[0].code == "dataset.source_changed"
    assert "`vqapr run alpha-001 --force`" in str(changed.value.failures[0].fix)


def test_verify_roster_names_the_table_it_cannot_read(tmp_path: Path) -> None:
    diagnosis, rows = validation.verify_roster({"stock": tmp_path / "absent.parquet"})

    assert rows == {}
    assert [failure.code for failure in diagnosis.failures] == ["roster.table_missing"]
    assert "readable instrument table" in diagnosis.failures[0].requirement
