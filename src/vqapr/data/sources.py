"""물리 배치 — 어디에 어떻게 쌓여 있나.

**이것은 선언(값)이고 파일을 열지 않는다.** 여는 것은 `scan.py`다. 여기에 I/O를 붙이면 등록 선언을
만드는 것만으로 파일이 열린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vqapr.domain.identifiers import SourceId, source_id


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """등록 대상 parquet의 위치와 읽는 방법.

    path              단일 parquet 파일 또는 디렉터리(하위 전부)
    hive_partitioned  hive 레이아웃이면 True. **장식이 아니라 읽는 방법을 바꾼다** —
                      False로 읽으면 파티션 키가 컬럼으로 나타나지 않고 가지치기도 없다

    형식은 parquet뿐이다. 원천을 여기까지 가져오는 것은 user 쪽 일이다(PRD §4.0).
    """

    source_id: SourceId
    path: Path
    hive_partitioned: bool = False

    @classmethod
    def of(cls, raw_id: str, path: str | Path, *, hive_partitioned: bool = False) -> SourceSpec:
        return cls(
            source_id=source_id(raw_id),
            path=Path(path),
            hive_partitioned=hive_partitioned,
        )
