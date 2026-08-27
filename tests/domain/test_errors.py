"""`domain/errors.py` — 실패를 기계가 읽을 수 있게."""

from __future__ import annotations

import json

import pytest

from vqapr.domain.errors import (
    MAX_EXAMPLES,
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
    collector,
)


def _failure(code: str, requirement: str, **overrides: object) -> Failure:
    """A refusal with the envelope filled in, so a test can vary the one field it is about."""
    fields: dict[str, object] = {
        "fix": "prepare the source and register again",
        "explain": ExplainTopic.DATASET_PREPARATION,
    }
    fields.update(overrides)
    return Failure.bounded(code, requirement, **fields)  # type: ignore[arg-type]


def test_one_error_carries_many_failures() -> None:
    """agent가 ETL을 고치려면 문제를 한 번에 다 받아야 한다."""
    c = collector("dataset.register.schema")
    c.add(_failure("dataset.register.schema.field_missing", "종가2"))
    c.add(_failure("dataset.register.schema.available_at_not_tz", "available_at"))
    with pytest.raises(VqaprError) as caught:
        c.done().raise_if_failed()
    assert len(caught.value.failures) == 2


def test_a_clean_collector_does_not_raise() -> None:
    diagnosis = collector("dataset.register.schema").done()
    assert diagnosis.ok
    diagnosis.raise_if_failed()


def test_examples_are_bounded_and_report_the_total() -> None:
    """8.7M행짜리 원천에서 예시가 무한히 실려 나가면 안 된다."""
    failure = _failure(
        "dataset.register.key.duplicate",
        "(거래일자, 종목약코드) must be unique",
        examples=[f"row-{i}" for i in range(5_000)],
    )
    assert len(failure.examples) == MAX_EXAMPLES
    assert failure.example_total == 5_000


def test_constructing_with_too_many_examples_is_refused() -> None:
    with pytest.raises(ValueError, match="bounded"):
        Failure(
            code="a.b",
            requirement="r",
            fix="f",
            explain=ExplainTopic.DATASET_PREPARATION,
            examples=tuple(f"e{i}" for i in range(99)),
        )


def test_failure_code_must_be_a_dotted_path() -> None:
    with pytest.raises(ValueError, match="dotted path"):
        Failure(
            code="not a path",
            requirement="r",
            fix="f",
            explain=ExplainTopic.DATASET_PREPARATION,
        )


def test_a_refusal_must_name_the_next_action() -> None:
    """`fix`가 비면 실패는 다시 진단으로 돌아간다 — 무엇을 할지가 사라진다."""
    with pytest.raises(ValueError, match="fix must name the next action"):
        Failure(
            code="a.b",
            requirement="r",
            fix="",
            explain=ExplainTopic.DATASET_PREPARATION,
        )


def test_a_refusal_must_say_what_was_required() -> None:
    with pytest.raises(ValueError, match="requirement must say"):
        Failure(
            code="a.b",
            requirement="",
            fix="f",
            explain=ExplainTopic.DATASET_PREPARATION,
        )


def test_source_defaults_to_saying_it_does_not_know() -> None:
    """자리를 모르는 실패가 자리를 지어내면 안 된다. 셋 다 None인 것이 정직한 답이다."""
    failure = _failure("a.b", "r")
    assert failure.source == FailureSource()
    assert failure.source.as_dict() == {"file": None, "key_path": None, "line": None}


def test_a_source_is_a_structure_not_a_formatted_string() -> None:
    """읽는 쪽이 정규식을 짜지 않아도 되게 하려는 것이 이 필드의 전부다."""
    failure = _failure(
        "declaration.read.key_missing",
        "datasets.prices must declare source_id",
        source=FailureSource(file="declarations/datasets.yaml", key_path="datasets.prices", line=7),
    )
    assert failure.source.as_dict() == {
        "file": "declarations/datasets.yaml",
        "key_path": "datasets.prices",
        "line": 7,
    }


def test_mutation_and_correlation_survive_serialisation() -> None:
    err = VqaprError(
        stage="account.commit",
        family=FailureFamily.VALUATION,
        failures=[
            _failure(
                "account.commit.nav",
                "mark required",
                explain=ExplainTopic.RUN_PRECONDITION,
            )
        ],
        mutation=True,
        retry_precondition="re-mark at the same account version",
    )
    payload = json.loads(json.dumps(err.as_dict()))
    assert payload["mutation"] is True
    assert payload["family"] == "VALUATION"
    assert payload["retry_precondition"]
    assert payload["correlation_id"] == err.correlation_id


def test_the_envelope_carries_every_field_through_serialisation() -> None:
    """agent는 이 여섯 개를 이름으로 읽는다. 하나라도 빠지면 계약이 깨진다."""
    err = VqaprError(
        stage="declaration.read",
        family=FailureFamily.DATA,
        failures=[
            _failure(
                "declaration.read.key_missing",
                "datasets.prices must declare source_id",
                observed="datasets.prices declares: path",
                source=FailureSource(file="datasets.yaml", key_path="datasets.prices", line=3),
                fix="add source_id to datasets.prices",
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        ],
    )

    entry = json.loads(json.dumps(err.as_dict()))["failures"][0]

    assert entry["code"] == "declaration.read.key_missing"
    assert entry["source"] == {"file": "datasets.yaml", "key_path": "datasets.prices", "line": 3}
    assert entry["requirement"] == "datasets.prices must declare source_id"
    assert entry["observed"] == "datasets.prices declares: path"
    assert entry["fix"] == "add source_id to datasets.prices"
    assert entry["explain"] == "declaration-shape"


def test_human_summary_lists_every_failure() -> None:
    err = VqaprError(
        stage="dataset.register.schema",
        family=FailureFamily.DATA,
        failures=[
            _failure("dataset.register.schema.field_missing", "종가2"),
            _failure("dataset.register.schema.available_at_not_tz", "available_at"),
        ],
    )
    text = str(err)
    assert "2 failure(s)" in text
    assert "field_missing" in text
    assert "available_at_not_tz" in text
