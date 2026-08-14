"""`domain/errors.py` — 실패를 기계가 읽을 수 있게."""

from __future__ import annotations

import json

import pytest

from vqapr.domain.errors import (
    MAX_EXAMPLES,
    Failure,
    FailureFamily,
    VqaprError,
    collector,
)


def test_one_error_carries_many_failures() -> None:
    """agent가 ETL을 고치려면 문제를 한 번에 다 받아야 한다."""
    c = collector("dataset.register.schema")
    c.add(Failure.bounded("dataset.register.schema.field_missing", "종가2"))
    c.add(Failure.bounded("dataset.register.schema.available_at_not_tz", "available_at"))
    with pytest.raises(VqaprError) as caught:
        c.done().raise_if_failed()
    assert len(caught.value.failures) == 2


def test_a_clean_collector_does_not_raise() -> None:
    diagnosis = collector("dataset.register.schema").done()
    assert diagnosis.ok
    diagnosis.raise_if_failed()


def test_examples_are_bounded_and_report_the_total() -> None:
    """8.7M행짜리 원천에서 예시가 무한히 실려 나가면 안 된다."""
    failure = Failure.bounded(
        "dataset.register.key.duplicate",
        "(거래일자, 종목약코드) must be unique",
        examples=[f"row-{i}" for i in range(5_000)],
    )
    assert len(failure.examples) == MAX_EXAMPLES
    assert failure.example_total == 5_000


def test_constructing_with_too_many_examples_is_refused() -> None:
    with pytest.raises(ValueError, match="bounded"):
        Failure(code="a.b", requirement="r", examples=tuple(f"e{i}" for i in range(99)))


def test_failure_code_must_be_a_dotted_path() -> None:
    with pytest.raises(ValueError, match="dotted path"):
        Failure(code="not a path", requirement="r")


def test_mutation_and_correlation_survive_serialisation() -> None:
    err = VqaprError(
        stage="account.commit",
        family=FailureFamily.VALUATION,
        failures=[Failure.bounded("account.commit.nav", "mark required")],
        mutation=True,
        retry_precondition="re-mark at the same account version",
    )
    payload = json.loads(json.dumps(err.as_dict()))
    assert payload["mutation"] is True
    assert payload["family"] == "VALUATION"
    assert payload["retry_precondition"]
    assert payload["correlation_id"] == err.correlation_id


def test_human_summary_lists_every_failure() -> None:
    err = VqaprError(
        stage="dataset.register.schema",
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded("dataset.register.schema.field_missing", "종가2"),
            Failure.bounded("dataset.register.schema.available_at_not_tz", "available_at"),
        ],
    )
    text = str(err)
    assert "2 failure(s)" in text
    assert "field_missing" in text
    assert "available_at_not_tz" in text
