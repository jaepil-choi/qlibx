"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.workspace import Workspace

__all__ = (
    "DatasetRegistration",
    "SourceSpec",
    "VqaprError",
    "register_dataset",
)


def register_dataset(
    project_root: str | Path,
    registration: DatasetRegistration,
    source: SourceSpec,
) -> bool:
    """준비된 parquet을 검증하고 project workspace에 등록한다.

    새 등록이면 ``True``, 디스크에 이미 같은 선언이 있으면 ``False``다. 검증이나 persistence가
    실패하면 ``VqaprError``를 발생시키며, 검증 실패는 workspace를 만들거나 바꾸지 않는다.
    """
    diagnosis, _ = validate(registration, source)
    diagnosis.raise_if_failed()
    return Workspace.create(project_root).register_dataset(registration, source)
