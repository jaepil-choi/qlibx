"""`domain/errors.py` — 실패를 기계가 읽을 수 있게.

Record `171`: a failure carries `status` (who must act, HTTP's numbers), the error carries
`stage` (which operation was under way), and every failure carries its `cause` whole.
"""

from __future__ import annotations

import json
import pickle

import pytest

from vqapr.domain.errors import (
    MAX_EXAMPLES,
    Cause,
    Failure,
    FailureSource,
    Stage,
    Status,
    VqaprError,
    collector,
    status_of,
    unhandled,
)


def _failure(code: str, requirement: str, **overrides: object) -> Failure:
    """A refusal with the envelope filled in, so a test can vary the one field it is about."""
    fields: dict[str, object] = {
        "status": Status.INVALID,
        "fix": "prepare the source and register again",
    }
    fields.update(overrides)
    return Failure.bounded(code, requirement, **fields)  # type: ignore[arg-type]


def _raised_here() -> ValueError:
    """An exception whose innermost frame is this test file: the user's, by `Cause`'s split."""
    try:
        raise ValueError("boom")
    except ValueError as error:
        return error


def _raised_in_the_framework() -> TypeError:
    """An exception whose innermost frame is under `src/vqapr`: `errors.py` refusing a stage
    that is a free string."""
    try:
        VqaprError(stage="bad", failures=[])  # type: ignore[arg-type]
    except TypeError as error:
        return error
    raise AssertionError("a free stage string must be refused")


# --- Status ---------------------------------------------------------------------------------


def test_status_numbers_are_http_s() -> None:
    """An agent knows what 404 and 409 mean before it opens this package."""
    assert {int(member) for member in Status} == {400, 404, 409, 412, 422, 423, 500, 502, 503}
    assert Status(404) is Status.MISSING
    assert Status.CRASHED == 502


def test_status_label_is_the_lowercase_name() -> None:
    assert [member.label for member in Status] == [
        "invalid",
        "missing",
        "conflict",
        "precondition",
        "contract",
        "locked",
        "internal",
        "crashed",
        "unavailable",
    ]


def test_five_hundreds_outrank_four_hundreds() -> None:
    """`VqaprError.status` takes the max, so the numbers must order by who has to act."""
    assert max(Status.INVALID, Status.CRASHED) is Status.CRASHED
    assert max(Status.LOCKED, Status.INTERNAL) is Status.INTERNAL
    assert all(five > four for five in Status if five >= 500 for four in Status if four < 500)


# --- Stage ----------------------------------------------------------------------------------


def test_stage_is_a_closed_set_of_operations() -> None:
    assert {str(member) for member in Stage} == {
        "usage",
        "open",
        "read",
        "register",
        "lookup",
        "remove",
        "write",
        "load",
        "check",
        "freeze",
        "run",
        "record",
    }
    assert Stage("run") is Stage.RUN


def test_an_error_refuses_a_free_stage_string() -> None:
    with pytest.raises(TypeError, match="stage must be a Stage, got str"):
        VqaprError(stage="dataset.register.schema", failures=[])  # type: ignore[arg-type]


# --- Failure --------------------------------------------------------------------------------


def test_bounded_requires_a_status() -> None:
    """`status` is keyword-only and has no default: a site cannot forget who must act."""
    with pytest.raises(TypeError, match="status"):
        Failure.bounded("a.b", "r", fix="f")  # type: ignore[call-arg]


def test_a_status_must_be_a_status_member() -> None:
    for wrong in (404, "missing"):
        with pytest.raises(TypeError, match="status must be a Status"):
            Failure(code="a.b", status=wrong, requirement="r", fix="f")  # type: ignore[arg-type]


def test_one_error_carries_many_failures() -> None:
    """agent가 ETL을 고치려면 문제를 한 번에 다 받아야 한다."""
    c = collector(Stage.REGISTER)
    c.add(_failure("dataset.field_missing", "종가2"))
    c.add(_failure("dataset.available_at_not_tz", "available_at"))
    with pytest.raises(VqaprError) as caught:
        c.done().raise_if_failed()
    assert len(caught.value.failures) == 2
    assert caught.value.stage is Stage.REGISTER


def test_a_clean_collector_does_not_raise() -> None:
    diagnosis = collector(Stage.REGISTER).done()
    assert diagnosis.ok
    diagnosis.raise_if_failed()


def test_examples_are_bounded_and_report_the_total() -> None:
    """8.7M행짜리 원천에서 예시가 무한히 실려 나가면 안 된다."""
    failure = _failure(
        "dataset.key_duplicate",
        "(거래일자, 종목약코드) must be unique",
        examples=[f"row-{i}" for i in range(5_000)],
    )
    assert len(failure.examples) == MAX_EXAMPLES
    assert failure.example_total == 5_000


def test_constructing_with_too_many_examples_is_refused() -> None:
    with pytest.raises(ValueError, match="bounded"):
        Failure(
            code="a.b",
            status=Status.INVALID,
            requirement="r",
            fix="f",
            examples=tuple(f"e{i}" for i in range(99)),
        )


def test_failure_code_must_be_a_dotted_path() -> None:
    with pytest.raises(ValueError, match="dotted path"):
        Failure(code="not a path", status=Status.INVALID, requirement="r", fix="f")


def test_a_refusal_must_name_the_next_action() -> None:
    """`fix`가 비면 실패는 다시 진단으로 돌아간다 — 무엇을 할지가 사라진다."""
    with pytest.raises(ValueError, match="fix must name the next action"):
        Failure(code="a.b", status=Status.INVALID, requirement="r", fix="")


def test_a_refusal_must_say_what_was_required() -> None:
    with pytest.raises(ValueError, match="requirement must say"):
        Failure(code="a.b", status=Status.INVALID, requirement="", fix="f")


def test_source_defaults_to_saying_it_does_not_know() -> None:
    """자리를 모르는 실패가 자리를 지어내면 안 된다. 셋 다 None인 것이 정직한 답이다."""
    failure = _failure("a.b", "r")
    assert failure.source == FailureSource()
    assert failure.source.as_dict() == {"file": None, "key_path": None, "line": None}


def test_a_source_is_a_structure_not_a_formatted_string() -> None:
    """읽는 쪽이 정규식을 짜지 않아도 되게 하려는 것이 이 필드의 전부다."""
    failure = _failure(
        "declaration.key_missing",
        "datasets.prices must declare source_id",
        source=FailureSource(file="declarations/datasets.yaml", key_path="datasets.prices", line=7),
    )
    assert failure.source.as_dict() == {
        "file": "declarations/datasets.yaml",
        "key_path": "datasets.prices",
        "line": 7,
    }


# --- Cause ----------------------------------------------------------------------------------


def test_a_refusal_without_an_exception_still_carries_where() -> None:
    """The line that decided to refuse is evidence too: an agent that suspects the classification
    rather than its submission needs it."""
    failure = _failure("a.b", "r")
    assert failure.cause is not None
    assert failure.cause.where
    assert "test_errors.py" in failure.cause.where
    assert failure.cause.where.endswith("(_failure)")
    # This file is outside `src/vqapr`, so the deciding frame is the user's.
    assert failure.cause.origin == "user"
    assert failure.cause.type is None
    assert failure.cause.message is None
    assert failure.cause.traceback is None


def test_a_direct_construction_without_a_cause_names_its_caller_too() -> None:
    """`Failure(...)` fills `cause` in `__post_init__`; `Cause.here` must skip `errors.py`'s own
    frames and the dataclass-generated `__init__` alike, and land on the line that constructed."""
    failure = Failure(code="a.b", status=Status.INVALID, requirement="r", fix="f")
    assert failure.cause is not None
    assert failure.cause.where is not None
    assert "test_errors.py" in failure.cause.where, failure.cause.where
    assert failure.cause.origin == "user"


def test_cause_of_an_exception_raised_in_this_file_is_the_users() -> None:
    cause = Cause.of(_raised_here())
    assert cause.type == "ValueError"
    assert cause.message == "boom"
    assert cause.origin == "user"
    assert cause.where is not None
    assert "test_errors.py" in cause.where
    assert cause.where.endswith("(_raised_here)")
    assert cause.traceback is not None
    assert cause.traceback.startswith("Traceback (most recent call last):")
    assert 'raise ValueError("boom")' in cause.traceback


def test_cause_of_an_exception_raised_under_src_vqapr_is_the_frameworks() -> None:
    cause = Cause.of(_raised_in_the_framework())
    assert cause.type == "TypeError"
    assert cause.origin == "framework"
    assert cause.where is not None
    # Framework paths are shortened relative to `src/`, so an agent can quote them upstream.
    assert cause.where.startswith("vqapr/domain/errors.py:")
    assert cause.where.endswith("(__init__)")
    assert cause.traceback is not None
    assert "stage must be a Stage" in cause.traceback


def test_a_traceback_is_never_truncated() -> None:
    """Beta: a traceback cut at eight lines is a traceback the reader cannot use.

    Two functions alternate so no two consecutive frames are identical; Python itself folds a
    straight recursion into `[Previous line repeated N more times]`, which is not truncation but
    would make the count below meaningless.
    """

    def left(depth: int) -> None:
        if depth == 0:
            raise RuntimeError("bottom")
        right(depth - 1)

    def right(depth: int) -> None:
        left(depth)

    try:
        left(20)
    except RuntimeError as error:
        cause = Cause.of(error)
    assert cause.traceback is not None
    assert cause.traceback.count("in left") + cause.traceback.count("in right") >= 41
    assert cause.traceback.endswith("RuntimeError: bottom\n")


def test_bounded_reads_the_cause_from_the_exception_itself() -> None:
    """A raise site writes `cause=error` and nothing more."""
    failure = _failure("source.unreadable", "readable parquet", cause=_raised_here())
    assert failure.cause is not None
    assert failure.cause.type == "ValueError"
    assert failure.cause.origin == "user"


def test_a_cause_must_be_a_cause() -> None:
    with pytest.raises(TypeError, match="cause must be a Cause"):
        Failure(
            code="a.b",
            status=Status.INVALID,
            requirement="r",
            fix="f",
            cause="ValueError: boom",  # type: ignore[arg-type]
        )


def test_cause_as_dict_key_order() -> None:
    assert list(Cause.of(_raised_here()).as_dict()) == [
        "type",
        "message",
        "where",
        "origin",
        "traceback",
    ]


# --- status_of and unhandled ----------------------------------------------------------------


def test_status_of_reads_whose_frame_raised() -> None:
    assert status_of(_raised_here()) is Status.CRASHED
    assert status_of(_raised_in_the_framework()) is Status.INTERNAL


def test_unhandled_renders_a_user_raise_as_502() -> None:
    failure = unhandled(_raised_here(), stage=Stage.RUN)
    assert failure.code == "unhandled"
    assert failure.status is Status.CRASHED
    assert failure.observed == "ValueError: boom"
    assert failure.cause is not None
    assert failure.cause.where is not None
    assert failure.cause.where in failure.fix
    assert "innermost frame is yours" in failure.fix
    assert failure.cause.traceback is not None
    assert "boom" in failure.cause.traceback


def test_unhandled_renders_a_framework_raise_as_500() -> None:
    failure = unhandled(_raised_in_the_framework(), stage=Stage.RUN)
    assert failure.code == "unhandled"
    assert failure.status is Status.INTERNAL
    assert failure.observed.startswith("TypeError: stage must be a Stage")
    assert "file an issue upstream" in failure.fix
    assert failure.cause is not None
    assert failure.cause.origin == "framework"


# --- VqaprError -----------------------------------------------------------------------------


def test_error_status_is_the_most_severe_among_its_failures() -> None:
    """5xx before 4xx, then by number: one crashed callback outranks any number of typos."""
    mixed = VqaprError(
        stage=Stage.CHECK,
        failures=[
            _failure("a.b", "r", status=Status.INVALID),
            _failure("c.d", "r", status=Status.CRASHED),
            _failure("e.f", "r", status=Status.MISSING),
        ],
    )
    assert mixed.status is Status.CRASHED

    only_4xx = VqaprError(
        stage=Stage.CHECK,
        failures=[
            _failure("a.b", "r", status=Status.INVALID),
            _failure("c.d", "r", status=Status.CONFLICT),
        ],
    )
    assert only_4xx.status is Status.CONFLICT

    assert VqaprError(stage=Stage.CHECK, failures=[]).status is Status.INTERNAL


def test_mutation_and_correlation_survive_serialisation() -> None:
    err = VqaprError(
        stage=Stage.RUN,
        failures=[_failure("account.nav", "mark required", status=Status.PRECONDITION)],
        mutation=True,
        retry_precondition="re-mark at the same account version",
    )
    payload = json.loads(json.dumps(err.as_dict()))
    assert payload["mutation"] is True
    assert payload["retry_precondition"]
    assert payload["correlation_id"] == err.correlation_id
    assert "family" not in payload


def test_the_envelope_carries_every_field_in_the_one_key_order() -> None:
    """agent는 이 키들을 이름으로 읽는다. 하나라도 빠지거나 순서가 바뀌면 계약이 깨진다."""
    err = VqaprError(
        stage=Stage.REGISTER,
        failures=[
            _failure(
                "declaration.key_missing",
                "datasets.prices must declare source_id",
                status=Status.INVALID,
                observed="datasets.prices declares: path",
                source=FailureSource(file="datasets.yaml", key_path="datasets.prices", line=3),
                fix="add source_id to datasets.prices",
            )
        ],
    )

    payload = err.as_dict()
    assert list(payload) == [
        "stage",
        "mutation",
        "retry_precondition",
        "correlation_id",
        "failures",
    ]
    assert payload["stage"] == "register"

    entry = json.loads(json.dumps(payload))["failures"][0]
    assert list(entry) == [
        "code",
        "status",
        "source",
        "requirement",
        "observed",
        "fix",
        "cause",
        "examples",
        "example_total",
    ]
    assert entry["code"] == "declaration.key_missing"
    assert entry["status"] == 400
    assert entry["source"] == {"file": "datasets.yaml", "key_path": "datasets.prices", "line": 3}
    assert entry["requirement"] == "datasets.prices must declare source_id"
    assert entry["observed"] == "datasets.prices declares: path"
    assert entry["fix"] == "add source_id to datasets.prices"
    assert list(entry["cause"]) == ["type", "message", "where", "origin", "traceback"]
    assert entry["cause"]["where"]
    assert entry["examples"] == []
    assert entry["example_total"] == 0
    assert "explain" not in entry


def test_human_summary_lists_every_failure_with_its_status() -> None:
    err = VqaprError(
        stage=Stage.REGISTER,
        failures=[
            _failure("dataset.field_missing", "종가2"),
            _failure("dataset.available_at_not_tz", "available_at", status=Status.PRECONDITION),
        ],
    )
    text = str(err)
    assert text.startswith("register: 2 failure(s)")
    assert "[400 dataset.field_missing]" in text
    assert "[412 dataset.available_at_not_tz]" in text


def test_the_error_survives_a_process_boundary() -> None:
    """A `--jobs` worker's refusal must come back to the parent as the same refusal (issue 073)."""
    original = VqaprError(
        stage=Stage.FREEZE,
        failures=[
            _failure(
                "account.mode",
                "a long-only account holds no short",
                status=Status.PRECONDITION,
                observed="-10 of A",
                cause=_raised_here(),
                examples=["A"],
            )
        ],
        mutation=True,
        retry_precondition="fix the initial account",
    )

    restored = pickle.loads(pickle.dumps(original))

    assert isinstance(restored, VqaprError)
    assert restored.stage is Stage.FREEZE
    assert restored.failures == original.failures
    assert restored.mutation is True
    assert restored.retry_precondition == "fix the initial account"
    assert restored.correlation_id == original.correlation_id
    assert restored.as_dict() == original.as_dict()
    assert str(restored) == str(original)
