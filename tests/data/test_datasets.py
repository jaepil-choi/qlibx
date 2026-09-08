"""`data/datasets.py` — 등록 선언과 네 단계 검증."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from vqapr.data import scan
from vqapr.data.datasets import (
    KEY_STAGE,
    SCHEMA_STAGE,
    VALUE_STAGE,
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
        "grain": "rows",
        "fields": {"close": "close", "session_date": "session_date"},
        # `conftest._ROWS` writes `close` as an integer literal, so the file holds an INTEGER.
        "field_types": {"close": "INTEGER", "session_date": "DATE"},
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
        _registration(
            available_at="session_date",
            fields={"close": "nope"},
            field_types={"close": "INTEGER"},
        ),
        spec,
    )
    codes = sorted(f.code for f in diagnosis.failures)
    assert codes == [
        f"{SCHEMA_STAGE}.available_at_not_a_timestamp",
        f"{SCHEMA_STAGE}.field_missing",
    ]


def test_a_failed_schema_skips_the_full_scan(hive_parquet: Path) -> None:
    """없는 컬럼 때문에 전체를 스캔할 이유가 없다."""
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    diagnosis, timing, _measured = validate(
        _registration(fields={"close": "nope"}, field_types={"close": "INTEGER"}), spec
    )
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
    with pytest.raises(ValueError, match="at least one value"):
        _registration(fields={}, field_types={})


def test_framework_names_may_not_contain_whitespace() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        _registration(fields={"close price": "close"}, field_types={"close price": "INTEGER"})


# --- 타입은 선언이고, 등록이 한 번 대조한다 (088) -----------------------------------------


def test_a_declaration_must_type_every_field_and_nothing_else() -> None:
    """`field_types`는 `fields`의 키를 정확히 덮는다: 빠져도, 남아도, 없어도 거절이다."""
    with pytest.raises(ValueError, match="field_types") as absent:
        _registration(field_types=None)
    assert "absent" in str(absent.value)
    with pytest.raises(ValueError, match="field_types") as untyped:
        _registration(field_types={"close": "INTEGER"})
    assert "session_date" in str(untyped.value)
    with pytest.raises(ValueError, match="field_types") as surplus:
        _registration(field_types={"close": "INTEGER", "session_date": "DATE", "open": "DOUBLE"})
    assert "open" in str(surplus.value)


def test_a_decimal_cannot_be_declared() -> None:
    """잴 수는 있어도 선언할 수는 없는 타입. 거절은 허용 목록을 댄다."""
    with pytest.raises(ValueError, match="field_types") as refused:
        _registration(field_types={"close": "DECIMAL", "session_date": "DATE"})
    message = str(refused.value)
    assert "DECIMAL" in message and "DOUBLE" in message and "INTEGER" in message


def test_a_declared_type_is_spelled_case_insensitively_or_as_the_enum() -> None:
    assert _registration(field_types={"close": "integer", "session_date": "date"}).field_types == {
        "close": scan.ColumnType.INTEGER,
        "session_date": scan.ColumnType.DATE,
    }
    assert _registration(
        field_types={"close": scan.ColumnType.INTEGER, "session_date": scan.ColumnType.DATE}
    ).field_types == {"close": scan.ColumnType.INTEGER, "session_date": scan.ColumnType.DATE}


def _typed_parquet(path: Path, close_type: pa.DataType) -> Path:
    """Two rows of one name, with `close` in the arrow type the test names."""
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "available_at": pa.array(
                [datetime(2024, 1, 2, 6, 30, tzinfo=UTC), datetime(2024, 1, 3, 6, 30, tzinfo=UTC)],
                pa.timestamp("us", tz="UTC"),
            ),
            "instrument": pa.array(["A", "A"], pa.string()),
            "close": pa.array([Decimal("100.5"), Decimal("101.5")], close_type)
            if pa.types.is_decimal(close_type)
            else pa.array([100.5, 101.5], close_type),
        }
    )
    pq.write_table(table, path)
    return path


def _typed(close_type: str) -> DatasetRegistration:
    return _registration(
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": close_type},
    )


def test_a_decimal_column_is_refused_whatever_it_is_declared_as(tmp_path: Path) -> None:
    """`decimal128(18,4)` declared DOUBLE: 접히지 않고, 파일의 타입 그대로 거절한다.

    2026-09-08 이전에는 DECIMAL이 DOUBLE로 접혀 등록은 통과하고 모델은 `Decimal`을 받았다.
    거절의 `observed`가 duckdb의 철자(`DECIMAL(18,4)`)를 들고 오므로 author는 어느 컬럼을
    어떻게 캐스팅할지 바로 안다.
    """
    spec = SourceSpec.of("s", _typed_parquet(tmp_path / "decimal.parquet", pa.decimal128(18, 4)))

    diagnosis, timing, _measured = validate(_typed("DOUBLE"), spec)

    assert [f.code for f in diagnosis.failures] == [f"{SCHEMA_STAGE}.field_decimal"]
    assert "DECIMAL(18,4)" in (diagnosis.failures[0].observed or "")
    assert "DOUBLE" in diagnosis.failures[0].fix
    assert timing.key_was_skipped is True


def test_a_declaration_that_disagrees_with_the_file_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    """float64 declared INTEGER: 어느 쪽이 틀렸는지는 author가 정하므로 둘 다 인용한다."""
    spec = SourceSpec.of("s", _typed_parquet(tmp_path / "double.parquet", pa.float64()))

    diagnosis, timing, _measured = validate(_typed("INTEGER"), spec)

    (failure,) = diagnosis.failures
    assert failure.code == f"{SCHEMA_STAGE}.field_type_mismatch"
    assert "INTEGER" in failure.requirement
    assert "DOUBLE" in (failure.observed or "")
    assert "field_types.close: DOUBLE" in failure.fix
    assert timing.key_was_skipped is True


def test_a_declaration_that_matches_the_file_carries_the_declared_types(tmp_path: Path) -> None:
    """통과한 등록의 `field_types`는 잰 값이 아니라 선언 그대로다."""
    spec = SourceSpec.of("s", _typed_parquet(tmp_path / "double.parquet", pa.float64()))

    diagnosis, _timing, measured = validate(_typed("DOUBLE"), spec)

    assert diagnosis.ok, [f.code for f in diagnosis.failures]
    assert measured.field_types == {"close": scan.ColumnType.DOUBLE}


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
            grain="rows",
            key_fields=("거래일자", "종목약코드"),
            fields={"close": "종가", "session_date": "거래일자"},
            field_types={"close": "INTEGER", "session_date": "DATE"},
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
            grain="rows",
            key_fields=("종목약코드",),
            fields={"close": "종가"},
            field_types={"close": "INTEGER"},
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


# --- 읽기 경로가 하던 검사가 여기로 옮겨 왔다 (044) ---------------------------------
#
# `normalize_scalar`이 읽는 셀마다 묻던 세 질문 -- 유한한가, tz-aware인가, 애초에 scalar인가
# -- 이 이제 등록에서 컬럼당 한 번 답해진다. `035`의 addendum이 경고한 것은 그 질문들을 읽기
# 경로에서 **지우기만** 하는 것이었고, 그러면 평가당 1.6s를 조용한 NaN과 맞바꾼다. 아래가
# 그 맞바꿈이 일어나지 않았다는 증거다.


_UNPREPARED_TYPES = {
    "close": "DOUBLE",
    "volume": "DOUBLE",
    "session_date": "DATE",
    # What their author would declare; each is refused by the measured type's own name.
    "stamped_at": "TIMESTAMP_TZ",
    "payload": "VARCHAR",
}
"""The declared type per `unprepared_parquet` column, keyed by the column a field exposes."""


def _exposing(**fields: str) -> DatasetRegistration:
    return _registration(
        key_fields=("session_date", "instrument"),
        fields=dict(fields),
        field_types={name: _UNPREPARED_TYPES[column] for name, column in fields.items()},
    )


def test_a_nan_column_is_refused_at_registration(unprepared_parquet: Path) -> None:
    """이 레인의 완료 조건.

    읽기 경로는 이제 아무것도 검증하지 않으므로, NaN이 model에 닿지 않는 유일한 이유가
    이것이다. NaN은 닿는 순간 실패하지 않는다 -- 만나는 모든 수로 번지고 run은 결과를
    보고한다. 그래서 파일이 등록되는 자리에서 거절한다.
    """
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, _timing, _measured = validate(_exposing(close="close"), spec)

    assert not diagnosis.ok
    assert diagnosis.stage == VALUE_STAGE
    assert [f.code for f in diagnosis.failures] == [f"{VALUE_STAGE}.not_finite"]


def test_the_refusal_names_the_field_and_counts_what_it_found(
    unprepared_parquet: Path,
) -> None:
    """거절이 "어딘가 NaN이 있다"로 끝나면 준비하는 쪽은 파일 전체를 다시 뒤진다."""
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, _timing, _measured = validate(_exposing(close="close"), spec)

    failure = diagnosis.failures[0]
    assert "'close'" in failure.requirement
    assert failure.example_total == 2, "NaN 하나와 inf 하나"
    assert 0 < len(failure.examples) <= MAX_EXAMPLES
    assert any("nan" in example for example in failure.examples)


def test_a_null_is_not_a_non_finite_value(unprepared_parquet: Path) -> None:
    """희소한 field는 정상이다.

    `volume`은 NULL을 담고 있고 통과해야 한다 -- 읽기 경로가 non-null만 세는 것과 같은
    뜻이다. NULL을 위반으로 세면 이 검사는 sparse panel 전부를 거절한다.
    """
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, _timing, measured = validate(_exposing(volume="volume"), spec)

    assert diagnosis.ok
    assert measured.span is not None


def test_a_naive_timestamp_field_is_refused_before_any_scan(
    unprepared_parquet: Path,
) -> None:
    """스키마가 이미 답한 것을 파일을 열어 다시 묻지 않는다.

    한 컬럼이 naive면 그 컬럼의 **모든** 행에 대해 참이다. 그래서 이것은 값 단계가 아니라
    1단계이고, 전체 스캔이 시작되기 전에 끝난다.
    """
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, timing, _measured = validate(_exposing(stamped_at="stamped_at"), spec)

    assert [f.code for f in diagnosis.failures] == [f"{SCHEMA_STAGE}.field_not_tz"]
    assert timing.key_was_skipped is True


def test_a_field_that_is_not_a_scalar_is_refused_before_any_scan(
    unprepared_parquet: Path,
) -> None:
    """model은 scalar의 행을 받는다. STRUCT를 건넬 portable한 방법이 없다."""
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, timing, _measured = validate(_exposing(payload="payload"), spec)

    assert [f.code for f in diagnosis.failures] == [f"{SCHEMA_STAGE}.field_not_portable"]
    assert timing.key_was_skipped is True


def test_only_the_exposed_columns_are_checked(unprepared_parquet: Path) -> None:
    """같은 파일이 NaN도 naive timestamp도 STRUCT도 담고 있지만, 지목되지 않으면 묻지 않는다.

    등록은 파일을 심사하는 것이 아니라 **선언이 약속한 것**을 심사한다. 노출되지 않는 컬럼은
    읽기 경로가 절대 건네지 않으므로 그것 때문에 등록이 막히면 안 된다.
    """
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, _timing, _measured = validate(_exposing(session_date="session_date"), spec)

    assert diagnosis.ok


def test_a_declaration_with_no_numeric_field_does_not_open_the_file_for_it(
    unprepared_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NaN을 담을 수 없는 컬럼에 NaN을 묻는 스캔은 비용만이다.

    `048`이 등록 비용이 선언 폭을 따라 늘어난다고 지목한 자리다. 여기서 같은 실수를 하지
    않는다는 것을 falsifiable하게 적어 둔다 -- 스캔이 돌면 이 테스트는 터진다.
    """

    def refuse(*args, **kwargs):
        raise AssertionError("numeric이 없는 등록이 유한성 스캔을 돌렸다")

    monkeypatch.setattr(scan, "finite_check", refuse)
    spec = SourceSpec.of("s", unprepared_parquet)
    diagnosis, _timing, _measured = validate(_exposing(session_date="session_date"), spec)

    assert diagnosis.ok
