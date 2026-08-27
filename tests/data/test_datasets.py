"""`data/datasets.py` — 등록 선언과 두 단계 검증."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.data import scan
from vqapr.data.datasets import (
    KEY_STAGE,
    SCHEMA_STAGE,
    DatasetRegistration,
    validate,
)
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import MAX_EXAMPLES, VqaprError


def _registration(**overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "fields": {"close": "close", "session_date": "session_date"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of("price_daily", "s", **kwargs)


def test_a_sound_declaration_passes_both_phases(hive_parquet: Path) -> None:
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    diagnosis, timing, _measured = validate(_registration(), spec)
    assert diagnosis.ok
    assert timing.key_was_skipped is False


def test_every_schema_problem_arrives_together(hive_parquet: Path) -> None:
    """agent는 왕복 한 번에 고칠 것을 전부 받아야 한다."""
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    diagnosis, _, _measured = validate(
        _registration(available_at="session_date", fields={"close": "nope"}), spec
    )
    codes = sorted(f.code for f in diagnosis.failures)
    assert codes == [
        f"{SCHEMA_STAGE}.available_at_not_a_timestamp",
        f"{SCHEMA_STAGE}.field_missing",
    ]


def test_a_failed_schema_skips_the_full_scan(hive_parquet: Path) -> None:
    """없는 컬럼 때문에 전체를 스캔할 이유가 없다."""
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    diagnosis, timing, _measured = validate(_registration(fields={"close": "nope"}), spec)
    assert not diagnosis.ok
    assert diagnosis.stage == SCHEMA_STAGE
    assert timing.key_was_skipped is True


def test_naive_timestamp_is_refused(naive_parquet: Path) -> None:
    """저장도 조회도 되지만 조용히 틀린다. 등록이 유일하게 잡을 수 있는 자리다."""
    spec = SourceSpec.of("s", naive_parquet)
    diagnosis, _, _measured = validate(_registration(), spec)
    assert [f.code for f in diagnosis.failures] == [f"{SCHEMA_STAGE}.available_at_not_tz"]
    assert diagnosis.failures[0].observed == "TIMESTAMP_NAIVE"


def test_a_missing_column_names_the_role_that_declared_it(hive_parquet: Path) -> None:
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    diagnosis, _, _measured = validate(_registration(instrument_field="ticker"), spec)
    assert "instrument_field" in diagnosis.failures[0].requirement


def test_key_problems_arrive_together(dup_parquet: Path) -> None:
    spec = SourceSpec.of("s", dup_parquet)
    diagnosis, timing, _measured = validate(_registration(), spec)
    codes = sorted(f.code for f in diagnosis.failures)
    assert codes == [f"{KEY_STAGE}.duplicate", f"{KEY_STAGE}.null"]
    assert timing.key_was_skipped is False


def test_key_failures_keep_the_total_beside_the_sample(dup_parquet: Path) -> None:
    spec = SourceSpec.of("s", dup_parquet)
    diagnosis, _, _measured = validate(_registration(key_fields=("instrument",)), spec)
    failure = next(f for f in diagnosis.failures if f.code.endswith("duplicate"))
    assert len(failure.examples) <= MAX_EXAMPLES
    assert failure.example_total >= len(failure.examples)


def test_failures_carry_a_retry_precondition(dup_parquet: Path) -> None:
    spec = SourceSpec.of("s", dup_parquet)
    diagnosis, _, _measured = validate(_registration(), spec)
    with pytest.raises(VqaprError) as caught:
        diagnosis.raise_if_failed()
    assert caught.value.retry_precondition
    assert caught.value.mutation is False


def test_declaration_refuses_an_empty_key() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        _registration(key_fields=())


def test_declaration_refuses_exposing_nothing() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        _registration(fields={})


def test_framework_names_may_not_contain_whitespace() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        _registration(fields={"close price": "close"})


def test_source_id_mismatch_fails_before_opening_the_source(tmp_path: Path) -> None:
    spec = SourceSpec.of("other", tmp_path / "does-not-exist")

    diagnosis, timing, _measured = validate(_registration(), spec)

    assert [failure.code for failure in diagnosis.failures] == [f"{SCHEMA_STAGE}.source_mismatch"]
    assert timing.key_was_skipped is True


@pytest.mark.real_data
def test_dev_dataset_registration_is_valid(dev_dataset: Path) -> None:
    spec = SourceSpec.of("fng_prices", dev_dataset, hive_partitioned=True)
    diagnosis, timing, _measured = validate(
        DatasetRegistration.of(
            "price_daily",
            "fng_prices",
            instrument_field="종목약코드",
            available_at="available_at",
            key_fields=("거래일자", "종목약코드"),
            fields={"close": "종가", "session_date": "거래일자"},
        ),
        spec,
    )
    assert diagnosis.ok, [f.code for f in diagnosis.failures]
    assert timing.key_was_skipped is False


@pytest.mark.real_data
def test_dev_dataset_rejects_a_weak_key(dev_dataset: Path) -> None:
    spec = SourceSpec.of("fng_prices", dev_dataset, hive_partitioned=True)
    diagnosis, _, _measured = validate(
        DatasetRegistration.of(
            "price_daily",
            "fng_prices",
            instrument_field="종목약코드",
            available_at="available_at",
            key_fields=("종목약코드",),
            fields={"close": "종가"},
        ),
        spec,
    )
    failure = next(f for f in diagnosis.failures if f.code.endswith("duplicate"))
    assert failure.example_total > 5000
    assert len(failure.examples) == MAX_EXAMPLES


def test_validation_measures_the_span_from_the_scan_it_already_ran(hive_parquet: Path) -> None:
    """The span is a measurement, not a declaration.

    It is taken during registration -- a second aggregate over the source, measured at about a
    quarter of the key scan -- so that every later read is free: `Workspace.span` answers from
    the stored declaration without opening the file.
    """
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    declared = _registration()
    assert declared.span is None, "the author declares no span; the framework measures it"

    diagnosis, _timing, measured = validate(declared, spec)

    assert diagnosis.ok
    assert measured.span is not None
    first, last = measured.span
    assert first <= last
    assert first.tzinfo is not None and last.tzinfo is not None
    # Everything else carries across untouched: measuring a span must not restate a declaration.
    assert measured.dataset_id == declared.dataset_id
    assert measured.key_fields == declared.key_fields
    assert dict(measured.fields) == dict(declared.fields)


def test_a_failed_validation_returns_the_registration_it_was_given(hive_parquet: Path) -> None:
    """Nothing was measured, so nothing is attached: the caller gets back what it passed."""
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    declared = _registration(instrument_field="ticker")

    diagnosis, _timing, returned = validate(declared, spec)

    assert not diagnosis.ok
    assert returned is declared
    assert returned.span is None


def test_the_measured_span_matches_the_data_it_was_read_from(hive_parquet: Path) -> None:
    """Falsifiable against the source rather than against itself.

    Comparing the span to the source's own distinct instants proves it names the real endpoints;
    asserting only that two datetimes came back would pass on any pair.
    """
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    _diagnosis, _timing, measured = validate(_registration(), spec)

    instants = sorted(
        value for value in scan.distinct_values(spec, "available_at") if value is not None
    )
    assert measured.span == (instants[0], instants[-1])


def test_span_endpoints_must_be_timezone_aware() -> None:
    """A naive endpoint does not say which venue's clock it is on, so spans could not compare."""
    naive = datetime(2024, 1, 2, 15, 30)
    aware = datetime(2024, 1, 2, 15, 30, tzinfo=UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        _registration().with_span(naive, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        _registration().with_span(aware, naive)


def test_a_span_must_be_ordered() -> None:
    """An end before its beginning is not a narrower span, it is a wrong one."""
    with pytest.raises(ValueError, match="ordered"):
        _registration().with_span(
            datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)
        )
