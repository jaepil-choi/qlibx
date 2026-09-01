"""읽기 경로는 아무것도 검증하지 않는다 — `docs/issues/044`, ruling은 `docs/issues/049`.

등록이 통과시킨 것은 그 뒤로 신뢰한다. 그래서 `DuckDbObservationStore.query`가 자기 parquet에서
방금 읽은 셀을 다시 검사하지 않고, 같은 여덟 개 컬럼 이름에 행마다 같은 질문을 하지도 않는다.

이 파일이 적어 두는 것은 **그 결과 무엇이 달라지고 무엇이 달라지지 않는가**이다. 값은 하나도
달라지지 않는다. 달라지는 것은, 등록 이후에 파일이 바뀌어 생긴 오류가 읽는 자리에서 잡히지
않는다는 것이다 -- 그것이 ruling이고, 대신 등록이 그 질문을 컬럼당 한 번 한다
(`tests/data/test_datasets.py`).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.rows import normalize_rows
from vqapr.public import (
    DataRequirement,
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
    register_dataset,
)

SESSIONS = (
    datetime(2024, 1, 2, 6, 30, tzinfo=UTC),
    datetime(2024, 1, 3, 6, 30, tzinfo=UTC),
)
INSTRUMENTS = ("AAA", "BBB")

_SCHEMA = pa.schema(
    [
        ("available_at", pa.timestamp("us", tz="UTC")),
        ("instrument", pa.string()),
        ("close", pa.float64()),
    ]
)


def _write(source: Path, closes: dict[tuple[datetime, str], float]) -> None:
    rows = [
        {"available_at": stamp, "instrument": name, "close": closes[(stamp, name)]}
        for stamp in SESSIONS
        for name in INSTRUMENTS
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA), source)


def _sound() -> dict[tuple[datetime, str], float]:
    return {
        (stamp, name): 100.0 + index + offset
        for index, stamp in enumerate(SESSIONS)
        for offset, name in enumerate(INSTRUMENTS)
    }


@pytest.fixture
def registered(tmp_path: Path) -> tuple[Workspace, Path]:
    """건전한 파일 위에 등록을 마친 workspace와, 그 파일 경로."""
    source = tmp_path / "prices.parquet"
    _write(source, _sound())
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", source),
    )
    return Workspace.open(tmp_path), source


def _read(space: Workspace) -> tuple[dict[str, object], ...]:
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=SESSIONS[-1],
        instruments=INSTRUMENTS,
        store=DuckDbObservationStore(space),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )
    return window.observations(requirement).rows


def test_the_rows_are_exactly_what_the_removed_pass_would_have_produced(
    registered: tuple[Workspace, Path],
) -> None:
    """제거가 값을 바꾸지 않았다는 것을 값으로 말한다.

    `normalize_rows`는 검증만 하고 통과시키는 값은 손대지 않았다. 그것이 사실이라면 그 pass를
    다시 통과시켜도 같은 것이 나와야 한다 -- 그리고 그 동치가 깨지는 날이 이 제거가 계약을
    바꾼 날이다.
    """
    space, _source = registered

    rows = _read(space)

    assert rows == normalize_rows(rows)
    assert isinstance(rows[0]["available_at"], datetime)
    assert rows[0]["available_at"].tzinfo is not None
    assert isinstance(rows[0]["close"], float)


def test_the_row_order_contract_survives_the_removal(
    registered: tuple[Workspace, Path],
) -> None:
    """`available_at` 다음 dataset의 key fields. cross-sectional 모델이 여기에 의존한다."""
    space, _source = registered

    rows = _read(space)

    ordered = sorted(rows, key=lambda row: (row["available_at"], str(row["instrument"])))
    assert list(rows) == ordered


def test_a_nan_that_appeared_after_registration_is_delivered_rather_than_refused(
    registered: tuple[Workspace, Path],
) -> None:
    """ruling을 실행 가능한 문장으로 적어 둔 것.

    등록이 통과시킨 파일이 그 뒤에 바뀌었다. 읽기 경로는 그것을 쫓지 않는다 -- 셀마다 되묻는
    비용이 평가당 수 초이고, 그 비용으로 사는 것은 이미 등록이 답한 질문의 반복뿐이기
    때문이다. 이 테스트가 실패로 뒤집히는 날은 검사가 읽기 경로로 돌아온 날이고, 그때
    되돌아오는 것은 안전이 아니라 `044`가 잰 비용이다.
    """
    space, source = registered
    corrupted = _sound()
    corrupted[(SESSIONS[-1], "AAA")] = float("nan")
    _write(source, corrupted)

    rows = _read(space)

    tainted = next(
        row for row in rows if row["instrument"] == "AAA" and row["available_at"] == SESSIONS[-1]
    )
    assert math.isnan(tainted["close"])
