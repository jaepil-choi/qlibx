"""The user's own files, refused in the envelope instead of around it.

`register`와 `run`은 사용자가 준 경로를 그대로 읽는다. 그 경로가 없거나, YAML이 mapping이 아니거나,
`new`가 이미 있는 파일을 덮어쓰게 되는 경우는 **framework가 깨진 것이 아니라 입력이 틀린 것**인데,
bare `FileNotFoundError`/`TypeError`/`FileExistsError`로 나가면 `envelope.py`가 stage를 알 수 없어
`stage:"unhandled"`로 표시한다. agent에게 그것은 "framework가 고장났다"는 신호이므로, 자기 파일을
고치는 대신 framework를 의심하게 만든다.

`family`는 `UsageError`와 같은 이유로 `None`이다. `FailureFamily`는 package 단계의 닫힌
집합인데(architecture §8.3) 이 실패들은 그 어느 단계에도 도달하지 못했다 — 읽히지 않은 파일은
어떤 단계에도 들어가지 않는다.

여기서도 remedy는 만들지 않는다. `requirement`는 무엇이 필요했는지, `observed`는 무엇을 봤는지만
말하고, 대화는 skill이 담당한다(PRD §2.6).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from vqapr.cli.envelope import BoundedRefusal
from vqapr.domain.errors import MAX_EXAMPLES, ExplainTopic, FailureSource

INPUT_STAGE = "cli.input"

MISSING = f"{INPUT_STAGE}.file_missing"
UNREADABLE = f"{INPUT_STAGE}.file_unreadable"
NOT_A_MAPPING = f"{INPUT_STAGE}.not_a_mapping"
EXISTS = f"{INPUT_STAGE}.file_exists"
INCOMPLETE = f"{INPUT_STAGE}.keys_missing"
VALUE_INVALID = f"{INPUT_STAGE}.value_invalid"


class InputError(BoundedRefusal):
    """사용자가 준 입력 자체가 거부된 경우. package 단계에는 도달하지 못했다."""

    def __init__(
        self,
        code: str,
        *,
        requirement: str,
        observed: str,
        retry: str | None = None,
        examples: Sequence[str] = (),
        source: FailureSource | None = None,
        fix: str | None = None,
        explain: ExplainTopic = ExplainTopic.DECLARATION_SHAPE,
    ) -> None:
        self.code = code
        self.requirement = requirement
        self.observed = observed
        self.retry = retry
        self.source = source if source is not None else FailureSource()
        # `retry` and `fix` answer the same question at two scales -- what to do about this
        # refusal -- and this class had `retry` before the envelope existed. Falling back to it
        # keeps every existing call site emitting a real `fix` instead of an empty one, rather
        # than requiring sixteen edits to say what the site already says.
        self.fix = fix or retry or "correct the input named above, then retry"
        self.explain = explain
        # 상한은 `Failure.bounded`와 같은 이유로 둔다. 잘린 뒤에도 전체 개수는 남긴다.
        self.examples = tuple(str(item) for item in examples[:MAX_EXAMPLES])
        self.example_total = len(examples)
        super().__init__(requirement)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": INPUT_STAGE,
            "family": None,
            "mutation": False,
            "retry_precondition": self.retry,
            "correlation_id": None,
            "failures": [
                {
                    # The same six fields a package refusal carries. A reader parses these by
                    # name, and a CLI-level refusal that shipped four of them made the envelope
                    # conditional on which layer happened to refuse -- which is precisely what a
                    # single documented shape exists to prevent.
                    "code": self.code,
                    "source": self.source.as_dict(),
                    "requirement": self.requirement,
                    "observed": self.observed,
                    "fix": self.fix,
                    "explain": str(self.explain),
                    "examples": list(self.examples),
                    "example_total": self.example_total,
                }
            ],
        }


def read_yaml_mapping(path: Path, *, what: str) -> dict[str, Any]:
    """Read one user-authored YAML document, or refuse in a way an agent can parse.

    `what`은 어느 문서인지 이름 붙인다. 명령이 파일 여러 개를 받게 되어도 어느 것이 문제인지
    envelope만 보고 알 수 있어야 한다.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise InputError(
            MISSING,
            requirement=f"{what} must exist at the given path",
            observed=f"no file at {path}",
            source=FailureSource(file=str(path)),
            retry="create the file, then retry",
        ) from error
    except OSError as error:
        raise InputError(
            UNREADABLE,
            requirement=f"{what} must be readable",
            observed=f"{path}: {error.strerror or error}",
            source=FailureSource(file=str(path)),
        ) from error

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        # YAML 파서의 문구는 줄/열을 담고 있어 그 자체가 증거다. 새로 쓰지 않는다.
        raise InputError(
            NOT_A_MAPPING,
            requirement=f"{what} must be valid YAML",
            observed=str(error).replace("\n", " "),
        ) from error

    if not isinstance(document, dict):
        raise InputError(
            NOT_A_MAPPING,
            requirement=f"{what} must be a YAML mapping",
            observed=f"{path} parsed as {type(document).__name__}",
            source=FailureSource(file=str(path)),
        )
    return document


def refuse_existing(path: Path, *, what: str) -> None:
    """Refuse to overwrite, naming the file rather than raising a bare `FileExistsError`.

    재실행은 agent가 가장 흔하게 하는 일이다(Spawn Gate가 rung마다 3회를 허용한다). 그 경로가
    `unhandled`로 나가면 재시도 자체가 framework 고장으로 보고된다.
    """
    if path.exists():
        raise InputError(
            EXISTS,
            requirement=f"{what} must not already exist",
            observed=f"{path} already exists",
            source=FailureSource(file=str(path)),
            retry="remove it or pass a different --out, then retry",
        )
