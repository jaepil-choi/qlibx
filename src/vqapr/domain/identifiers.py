"""이름 — 무엇을 부르는가."""

from __future__ import annotations

from typing import NewType

DatasetId = NewType("DatasetId", str)
SourceId = NewType("SourceId", str)
InstrumentId = NewType("InstrumentId", str)
ExecutionInputId = NewType("ExecutionInputId", str)


def _clean(kind: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{kind} must be a string, got {type(raw).__name__}")
    if raw == "":
        raise ValueError(f"{kind} must not be empty")
    if raw != raw.strip():
        raise ValueError(f"{kind} must not have leading or trailing whitespace: {raw!r}")
    return raw


def dataset_id(raw: str) -> DatasetId:
    """등록된 dataset의 이름. project 안에서 사람이 고르는 손잡이다."""
    value = _clean("dataset_id", raw)
    if any(c.isspace() for c in value):
        raise ValueError(f"dataset_id must not contain whitespace: {value!r}")
    return DatasetId(value)


def source_id(raw: str) -> SourceId:
    """물리 원천의 이름."""
    value = _clean("source_id", raw)
    if any(c.isspace() for c in value):
        raise ValueError(f"source_id must not contain whitespace: {value!r}")
    return SourceId(value)


def execution_input_id(raw: str) -> ExecutionInputId:
    """한 project 안에서 고정한 execution-table + fill declaration의 이름."""
    value = _clean("execution_input_id", raw)
    if any(c.isspace() for c in value):
        raise ValueError(f"execution_input_id must not contain whitespace: {value!r}")
    return ExecutionInputId(value)


def instrument_id(raw: str) -> InstrumentId:
    """종목 식별자.

    **venue가 주는 형태를 그대로 받는다.** 경로 구분자를 막지 않는다 — NYSE는 `BRK/B`처럼
    슬래시가 든 티커를 준다. 공백만 거부하는 이유는 그것이 파싱 사고의 흔적이지 식별자의 일부인
    경우가 없기 때문이다.

    합성 instrument(`_KOSPI`, `_CD91`)도 같은 규칙을 통과한다.
    """
    value = _clean("instrument_id", raw)
    if any(c.isspace() for c in value):
        raise ValueError(f"instrument_id must not contain whitespace: {value!r}")
    return InstrumentId(value)
