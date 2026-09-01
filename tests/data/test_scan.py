"""`data/scan.py` — 물리 층을 여는 유일한 곳."""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import MAX_EXAMPLES, VqaprError


def test_describe_normalises_types_and_keeps_tz_distinct(hive_parquet: Path) -> None:
    cols = scan.describe(SourceSpec.of("s", hive_parquet, hive_partitioned=True))
    assert cols["instrument"] is scan.ColumnType.VARCHAR
    assert cols["session_date"] is scan.ColumnType.DATE
    assert cols["available_at"] is scan.ColumnType.TIMESTAMP_TZ
    assert cols["close"] is scan.ColumnType.INTEGER


def test_naive_timestamp_is_not_reported_as_tz_aware(naive_parquet: Path) -> None:
    """이 구분이 이 enum의 존재 이유다. naive는 저장도 조회도 되지만 조용히 틀린다."""
    cols = scan.describe(SourceSpec.of("s", naive_parquet))
    assert cols["available_at"] is scan.ColumnType.TIMESTAMP_NAIVE


def test_hive_declaration_changes_what_is_read(hive_parquet: Path) -> None:
    """`hive_partitioned`는 장식이 아니다 — 선언하지 않으면 파티션 키가 컬럼으로 없다."""
    on = scan.describe(SourceSpec.of("s", hive_parquet, hive_partitioned=True))
    off = scan.describe(SourceSpec.of("s", hive_parquet, hive_partitioned=False))
    assert "year" in on
    assert "year" not in off


def test_flat_and_hive_expose_the_same_business_columns(
    hive_parquet: Path, flat_parquet: Path
) -> None:
    """단일 parquet과 hive가 같은 것을 준다. 파티션 키만 더 붙는다."""
    hive = scan.describe(SourceSpec.of("s", hive_parquet, hive_partitioned=True))
    flat = scan.describe(SourceSpec.of("s", flat_parquet))
    assert set(hive) - set(flat) == {"year"}
    assert all(flat[c] is hive[c] for c in flat)


def test_distinct_values_is_a_sorted_physical_scan(flat_parquet: Path) -> None:
    values = scan.distinct_values(SourceSpec.of("s", flat_parquet), "session_date")

    assert [value.isoformat() for value in values] == [
        "2024-01-02",
        "2024-01-03",
        "2025-01-02",
    ]


def test_key_check_passes_on_a_real_key(hive_parquet: Path) -> None:
    result = scan.key_check(
        SourceSpec.of("s", hive_parquet, hive_partitioned=True), ("session_date", "instrument")
    )
    assert result.ok
    assert result.null_groups == 0
    assert result.duplicate_groups == 0


def test_key_check_reports_duplicates_and_nulls_together(dup_parquet: Path) -> None:
    result = scan.key_check(SourceSpec.of("s", dup_parquet), ("session_date", "instrument"))
    assert not result.ok
    assert result.duplicate_groups == 3
    assert result.null_groups == 1
    assert result.duplicate_examples
    assert result.null_examples


def test_key_check_bounds_its_examples(dup_parquet: Path) -> None:
    result = scan.key_check(SourceSpec.of("s", dup_parquet), ("instrument",))
    assert len(result.duplicate_examples) <= MAX_EXAMPLES


def test_key_check_rejects_an_empty_key(hive_parquet: Path) -> None:
    with pytest.raises(ValueError, match="at least one field"):
        scan.key_check(SourceSpec.of("s", hive_parquet), ())


def test_missing_path_is_machine_readable(tmp_path: Path) -> None:
    spec = SourceSpec.of("nope", tmp_path / "absent")
    with pytest.raises(VqaprError) as caught:
        scan.describe(spec)
    err = caught.value
    assert err.mutation is False
    assert err.retry_precondition
    assert [f.code for f in err.failures] == ["source.scan.path_missing"]
    assert err.as_dict()["failures"][0]["observed"] == str(spec.path)


def test_unreadable_source_is_machine_readable(tmp_path: Path) -> None:
    junk = tmp_path / "not.parquet"
    junk.write_text("definitely not parquet", encoding="utf-8")
    with pytest.raises(VqaprError) as caught:
        scan.describe(SourceSpec.of("junk", junk))
    assert [f.code for f in caught.value.failures] == ["source.scan.unreadable"]


@pytest.mark.real_data
def test_dev_dataset_satisfies_the_registration_contract(dev_dataset: Path) -> None:
    """실데이터 8.7M행. 계약이 요구하는 셋이 실제로 성립하는가."""
    spec = SourceSpec.of("fng_prices", dev_dataset, hive_partitioned=True)
    cols = scan.describe(spec)
    assert cols["available_at"] is scan.ColumnType.TIMESTAMP_TZ
    assert cols["거래일자"] is scan.ColumnType.DATE
    result = scan.key_check(spec, ("거래일자", "종목약코드"))
    assert result.ok


@pytest.mark.real_data
def test_dev_dataset_rejects_an_insufficient_key(dev_dataset: Path) -> None:
    spec = SourceSpec.of("fng_prices", dev_dataset, hive_partitioned=True)
    result = scan.key_check(spec, ("종목약코드",))
    assert not result.ok
    assert result.duplicate_groups > 5000
    assert len(result.duplicate_examples) == MAX_EXAMPLES


def test_finite_check_counts_every_column_without_reading_the_file_twice(
    unprepared_parquet: Path,
) -> None:
    """폭이 넓다고 스캔이 늘지 않는다 -- 컬럼당 스캔이 아니라 컬럼당 aggregate다.

    통과하는 컬럼은 결과에 나타나지도 않는다. 위반한 것만 이름과 개수를 갖는다.
    """
    spec = SourceSpec.of("s", unprepared_parquet)

    result = scan.finite_check(
        spec, columns=("close", "volume"), identity_fields=("instrument", "available_at")
    )

    assert not result.ok
    assert result.non_finite == (("close", 2),)
    assert dict(result.examples).keys() == {"close"}


def test_finite_check_reports_the_instant_and_the_name_a_bad_value_sits_on(
    unprepared_parquet: Path,
) -> None:
    """예시가 값만 말하면 준비하는 쪽은 그 행을 찾을 수 없다."""
    spec = SourceSpec.of("s", unprepared_parquet)

    result = scan.finite_check(
        spec, columns=("close",), identity_fields=("instrument", "available_at")
    )

    examples = dict(result.examples)["close"]
    assert len(examples) <= MAX_EXAMPLES
    assert any("A005930" in example for example in examples)


def test_finite_check_passes_a_column_that_only_carries_nulls_and_numbers(
    unprepared_parquet: Path,
) -> None:
    spec = SourceSpec.of("s", unprepared_parquet)

    result = scan.finite_check(
        spec, columns=("volume",), identity_fields=("instrument", "available_at")
    )

    assert result.ok
    assert result.examples == ()


def test_finite_check_refuses_to_be_asked_about_nothing(unprepared_parquet: Path) -> None:
    spec = SourceSpec.of("s", unprepared_parquet)
    with pytest.raises(ValueError, match="at least one column"):
        scan.finite_check(spec, columns=(), identity_fields=("instrument",))
