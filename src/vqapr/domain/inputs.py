"""The user's own files, refused in the envelope instead of around it.

`domain/` since record `193`. This is failure vocabulary -- it imports `domain.errors` and
nothing else -- and its readers sit at three different altitudes: `cli/` (ten call sites),
the declaration layer, and `extension/lookback.py`. A module every layer reads and none owns
is what `domain/` is for; at the top level it was a flat module the layer table could only
place by guessing.


`register`와 `run`은 사용자가 준 경로를 그대로 읽는다. 그 경로가 없거나, YAML이 mapping이 아니거나,
`new`가 이미 있는 파일을 덮어쓰게 되는 경우는 **framework가 깨진 것이 아니라 입력이 틀린 것**인데,
bare `FileNotFoundError`/`TypeError`/`FileExistsError`로 나가면 `envelope.py`가 stage를 알 수 없어
`stage:"unhandled"`로 표시한다. agent에게 그것은 "framework가 고장났다"는 신호이므로, 자기 파일을
고치는 대신 framework를 의심하게 만든다.

The stage is `Stage.USAGE` (record `171`): the argument never reached the package, so the
operation under way was the command line itself. Each code carries the `Status` that says who
must act -- a missing file is 404, an unreadable one 503, a wrong shape 400 -- and the failure
carries its cause whole: the `OSError` or `YAMLError` that was in hand, or the line that refused.

여기서도 remedy는 만들지 않는다. `requirement`는 무엇이 필요했는지, `observed`는 무엇을 봤는지만
말하고, 대화는 skill이 담당한다(PRD §2.6).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from vqapr.domain.errors import (
    MAX_EXAMPLES,
    Cause,
    Failure,
    FailureSource,
    Stage,
    Status,
)

INPUT_STAGE = Stage.USAGE

MISSING = "argument.file_missing"
UNREADABLE = "argument.file_unreadable"
NOT_A_MAPPING = "argument.not_a_mapping"
EXISTS = "argument.file_exists"
INCOMPLETE = "argument.keys_missing"
VALUE_INVALID = "argument.value_invalid"

_STATUS_BY_CODE: dict[str, Status] = {
    MISSING: Status.MISSING,
    UNREADABLE: Status.UNAVAILABLE,
    NOT_A_MAPPING: Status.INVALID,
    EXISTS: Status.CONFLICT,
    INCOMPLETE: Status.INVALID,
    VALUE_INVALID: Status.INVALID,
}
"""The status each shared code carries. A site raising a code of its own passes `status=`."""


# `BoundedRefusal` moved here from `cli/envelope.py` by record `112`. It is the base type for a
# refusal whose body is already bounded, and layers below the CLI raise it -- `flow/run_spec.py`
# and `vqapr/declarations.py` both do. Leaving it in the CLI meant a layer importing its own
# refusal vocabulary closed an import cycle through every verb module. `cli/envelope.py` still
# renders it; it no longer owns it.
class BoundedRefusal(Exception):
    """입력이 package 단계에 도달하기 전에 거부된 경우.

    이런 실패의 본문은 이미 유계다 — 요구한 것과 관찰한 것이 전부다. 원인(`cause`)은 그 본문
    안의 한 항목으로 실려 나가고(record `171`), 봉투는 그 밖에 아무것도 덧붙이지 않는다: 읽기만
    하는 명령이 거부하면서 `.vqapr/`에 dump 파일을 만드는 일은 없다. 거부가 부작용을 남기는
    것은 거부가 아니다.

    `failure()`는 이 타입을 본문만 실어 내보낸다.
    """

    def as_dict(self) -> dict[str, Any]:
        raise NotImplementedError


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
        status: Status | None = None,
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
        # The six shared codes know their status; a site with a code of its own says it. A code
        # that is neither is a programming error, and it is refused here, at construction.
        self.status = status if status is not None else _STATUS_BY_CODE[code]
        # 상한은 `Failure.bounded`와 같은 이유로 둔다. 잘린 뒤에도 전체 개수는 남긴다.
        self.examples = tuple(str(item) for item in examples[:MAX_EXAMPLES])
        self.example_total = len(examples)
        # The `raise InputError(...)` line, one frame out from this constructor.
        self.raised_at = Cause.here(skip=1)
        super().__init__(requirement)

    def as_failure(self) -> Failure:
        """This refusal as the package's own `Failure`, so it renders through the one shape.

        The same fields a package refusal carries. A reader parses these by name, and a CLI-level
        refusal that shipped four of them made the envelope conditional on which layer happened to
        refuse -- which is precisely what a single documented shape exists to prevent. `check`
        renders an `InputError` through this too, rather than through a second literal of its own.

        The cause is the exception this refusal was raised `from`, when there was one -- the
        `FileNotFoundError`, the `YAMLError` -- whole; otherwise `Failure` records the line that
        decided to refuse.
        """
        # Already bounded in `__init__`, so the direct constructor rather than `bounded`: cutting
        # the examples again would report `example_total` against a list cut twice.
        return Failure(
            code=self.code,
            status=self.status,
            requirement=self.requirement,
            fix=self.fix,
            source=self.source,
            observed=self.observed,
            cause=self.raised_at if self.__cause__ is None else Cause.of(self.__cause__),
            examples=self.examples,
            example_total=self.example_total,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": str(INPUT_STAGE),
            "mutation": False,
            "retry_precondition": self.retry,
            "correlation_id": None,
            "failures": [self.as_failure().as_dict()],
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
