"""실패를 기계가 읽을 수 있게 한다.

첫 사용자가 agent이므로 실패는 **읽는 것이 아니라 파싱하는 것**이어야 한다. 그리고 agent가 자기
준비 과정을 고치려면 문제를 하나씩이 아니라 **한 번에 다** 받아야 한다 — 그래서 예외 하나가
`Failure` 여럿을 담는다.

Record `171` rebuilt the vocabulary on the HTTP principle. A failure carries three things an
agent branches on, in this order:

- `status` -- WHO must act, a closed set with HTTP's numbers so an agent already knows them.
  4xx: the submission (a declaration, an argument, a data file, a precondition) is wrong; fix
  it before retrying. 5xx: the submission is fine; something that ran failed -- the user's own
  code (502), the framework (500), or the machine (503). An unknown `code` is handled as its
  status, the way an HTTP client treats an unknown 4xx as 400.
- `stage` -- WHICH operation was under way, a closed set: opening the workspace, registering,
  looking a reference up, checking, freezing, running, ...
- `cause` -- WHAT actually happened, whole. The taxonomy above is not guaranteed to be MECE in
  beta, so every failure carries its raw cause: the exception's type, message and full
  traceback when there was one, and always the file:line the refusal was raised from. An agent
  reads `status` to decide quickly and `cause` to decide correctly, including whether the
  fault is upstream's.
"""

from __future__ import annotations

import sys
import traceback
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from types import FrameType, TracebackType

MAX_EXAMPLES = 5
"""위반 예시 상한. 8.7M행짜리 원천에서 예시가 무한히 실려 나가면 안 된다(PRD §2.6)."""

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
"""`src/vqapr`: a traceback frame under here is the framework's; one elsewhere that is not the
interpreter's own is the user's. `Cause.of` reads origin from this split."""


class Status(IntEnum):
    """Who must act. HTTP's numbers, on purpose: an agent knows what 404 and 409 mean already.

    4xx -- the submission is wrong; retrying without changing it is pointless.
    5xx -- the submission is fine; look at what ran (the user's code, the framework, the
    machine). The number says which of the three, which is the question an agent asks first:
    is this mine to fix, or do I file an issue upstream?
    """

    INVALID = 400
    """The shape of what was handed in does not meet the contract: a declaration key, an
    argument, a parquet schema."""

    MISSING = 404
    """A name was given and nothing registered answers to it, or the path it names is not
    there."""

    CONFLICT = 409
    """What is being registered or removed disagrees with what the workspace already holds."""

    PRECONDITION = 412
    """The declaration is well-formed but a condition of running it does not hold: a lookback
    before the data starts, a decision at or after its fill, an account that contradicts its
    mode. What `vqapr check` is for."""

    CONTRACT = 422
    """The user's code is not something the framework can call, or what it returned is not
    something the framework can use: a wrong type, a missing method, an output with an
    instrument nobody asked for."""

    LOCKED = 423
    """Another process holds it: the workspace document, a live run record."""

    INTERNAL = 500
    """The framework itself failed. Not the user's to fix; file it upstream with `cause`."""

    CRASHED = 502
    """The user's own code raised while the framework was running it -- the gateway's upstream
    failed. `cause.where` names the user's line."""

    UNAVAILABLE = 503
    """The machine refused: a file could not be read or written, a disk was full."""

    @property
    def label(self) -> str:
        """`invalid`, `missing`, ...: the word beside the number in messages and the skill."""
        return self.name.lower()


class Stage(StrEnum):
    """Which operation was under way when the refusal was raised. Closed."""

    USAGE = "usage"
    """The command line itself, before any argument reached the package."""
    OPEN = "open"
    """Opening the workspace document."""
    READ = "read"
    """Reading a declared source, roster or record file from disk."""
    REGISTER = "register"
    """Proving and writing a declaration: dataset, execution dataset, component, run."""
    LOOKUP = "lookup"
    """Resolving a reference the workspace should hold."""
    REMOVE = "remove"
    """Removing a registration."""
    WRITE = "write"
    """Writing the workspace document."""
    LOAD = "load"
    """Importing and constructing a user component from its source file."""
    CHECK = "check"
    """The judgments `vqapr check` makes and `vqapr run` repeats."""
    FREEZE = "freeze"
    """Freezing a run's authority before it executes (preflight)."""
    RUN = "run"
    """Executing a frozen run: the callbacks, fills, valuations, datamodel computations."""
    RECORD = "record"
    """Writing a run's record or a datamodel's dataset."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FailureSource:
    """실패가 가리키는 자리. 포맷된 문자열이 아니라 **구조**다.

    `check`·`show`·skill이 이것을 다시 파싱하지 않고 쓰기 때문이다. "file.yaml:12의 datasets.x"
    같은 한 줄로 실으면 읽는 쪽이 정규식을 짜야 하고, 그 정규식은 문구가 바뀌는 날 조용히
    틀린다.

    셋 다 없을 수 있다: 실패가 파일이 아니라 값에서 났다면 `file`이 없고, 문서 전체에
    해당하면 `key_path`가 없으며, YAML이 줄 번호를 주지 않으면 `line`이 없다. 없는 것을
    지어내는 것보다 없다고 말하는 편이 낫다.
    """

    file: str | None = None
    key_path: str | None = None
    line: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {"file": self.file, "key_path": self.key_path, "line": self.line}


def _is_framework_frame(filename: str) -> bool:
    try:
        return Path(filename).resolve().is_relative_to(_PACKAGE_ROOT)
    except (OSError, ValueError):
        return False


def _is_interpreter_frame(filename: str) -> bool:
    """stdlib, site-packages, the REPL: neither the framework's nor the user's."""
    if filename.startswith("<"):
        return True
    lowered = filename.replace("\\", "/").lower()
    if "/site-packages/" in lowered or "/lib/python" in lowered:
        return True
    prefix = Path(sys.base_prefix).resolve()
    try:
        return Path(filename).resolve().is_relative_to(prefix)
    except (OSError, ValueError):
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class Cause:
    """What actually happened, whole. Every failure carries one.

    `type`, `message` and `traceback` are the exception as Python itself would print it, when
    there was an exception; `where` is the innermost frame that is not the interpreter's,
    `file:line (function)`; `origin` says whose frame that is -- `"user"` for a file outside
    the package, `"framework"` for one inside it, `None` when no frame was found. A refusal the
    framework raised deliberately, without an exception, still carries `where` and `origin`:
    the line that decided to refuse is evidence too, and it is what an agent needs when it
    suspects the classification rather than the submission.

    Nothing here is truncated. This is beta, and a traceback cut at eight lines is a
    traceback the reader cannot use.
    """

    type: str | None = None
    message: str | None = None
    where: str | None = None
    origin: str | None = None
    traceback: str | None = None

    @classmethod
    def of(cls, error: BaseException) -> Cause:
        """The cause of an exception, read from its traceback."""
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        where, origin = _innermost(error.__traceback__)
        return cls(
            type=type(error).__name__,
            message=str(error),
            where=where,
            origin=origin,
            traceback=text,
        )

    @classmethod
    def here(cls, *, skip: int = 0) -> Cause:
        """The framework line that decided to refuse, for a failure with no exception.

        `skip` steps that many further frames out, for a constructor that wants to name the
        `raise` line rather than itself (`InputError.__init__` passes 1).
        """
        frame = sys._getframe(1)
        here = Path(__file__).resolve()

        def _outward(current: FrameType | None) -> FrameType | None:
            # Skip this module's own frames and the interpreter's: a dataclass-generated
            # `__init__` lives in `<string>`, and a direct `Failure(...)` passes through it.
            while current is not None and (
                _is_interpreter_frame(current.f_code.co_filename)
                or Path(current.f_code.co_filename).resolve() == here
            ):
                current = current.f_back
            return current

        frame = _outward(frame)
        for _ in range(skip):
            frame = _outward(None if frame is None else frame.f_back)
        if frame is None:
            return cls()
        filename = frame.f_code.co_filename
        return cls(
            where=f"{_short(filename)}:{frame.f_lineno} ({frame.f_code.co_name})",
            origin="framework" if _is_framework_frame(filename) else "user",
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "message": self.message,
            "where": self.where,
            "origin": self.origin,
            "traceback": self.traceback,
        }


def _short(filename: str) -> str:
    try:
        return Path(filename).resolve().relative_to(_PACKAGE_ROOT.parent).as_posix()
    except ValueError:
        return filename


def _innermost(tb: TracebackType | None) -> tuple[str | None, str | None]:
    """The innermost non-interpreter frame of a traceback, and whose it is.

    A user frame wins over a framework frame when both are present below the interpreter's:
    the innermost frame is where the exception was raised, and if that is the user's file the
    user's code crashed (502) even though framework frames sit above it.
    """
    frames = traceback.extract_tb(tb) if tb is not None else []
    for summary in reversed(frames):
        if _is_interpreter_frame(summary.filename):
            continue
        origin = "framework" if _is_framework_frame(summary.filename) else "user"
        return f"{_short(summary.filename)}:{summary.lineno} ({summary.name})", origin
    return None, None


def status_of(error: BaseException) -> Status:
    """500 or 502 for an exception nobody classified: whose frame raised it."""
    _, origin = _innermost(error.__traceback__)
    return Status.CRASHED if origin == "user" else Status.INTERNAL


@dataclass(frozen=True, slots=True, kw_only=True)
class Failure:
    """충족되지 않은 요구 하나. **진단이 아니라 지시**다.

    code        `<subject>.<detail>`: which thing, and what about it. 접두사로 분류하지 않는다 --
                분류는 `status`가 한다. 예: "dataset.field_missing"
    status      누가 고쳐야 하나. `Status`, 닫힌 집합
    source      어느 자리인가 — 파일·키·줄. 포맷된 문자열이 아니라 구조다
    requirement 무엇을 요구했나
    observed    실제로 무엇을 봤나. 없으면 None
    fix         **이번 한 번을 고치는 문장.** 다음에 무엇을 할지가 여기 있다
    cause       실제로 무엇이 일어났나 -- 예외 전문, 또는 거절을 낸 프레임워크의 줄. 항상 있다
    examples    위반 예시. MAX_EXAMPLES개로 잘린다
    example_total 잘리기 전 전체 개수. 예시가 전부인지 일부인지 알 수 있어야 한다

    `kw_only=True`가 붙은 이유는 문법이지 취향이 아니다: 기본값을 갖는 필드 뒤에 기본값 없는
    필드를 붙이면 dataclass가 **클래스 정의 시점에** TypeError를 낸다.
    """

    code: str
    status: Status
    requirement: str
    fix: str
    source: FailureSource = FailureSource()
    observed: str | None = None
    cause: Cause | None = None
    examples: tuple[str, ...] = ()
    example_total: int = 0

    def __post_init__(self) -> None:
        if not self.code or " " in self.code:
            raise ValueError(f"failure code must be a dotted path without spaces: {self.code!r}")
        if not isinstance(self.status, Status):
            raise TypeError(
                f"{self.code}: status must be a Status, got {type(self.status).__name__}"
            )
        if not self.requirement:
            raise ValueError(f"{self.code}: requirement must say what was required")
        if not self.fix:
            raise ValueError(f"{self.code}: fix must name the next action, not restate the problem")
        if not isinstance(self.source, FailureSource):
            raise TypeError(
                f"{self.code}: source must be a FailureSource, got {type(self.source).__name__}"
            )
        if len(self.examples) > MAX_EXAMPLES:
            raise ValueError(
                f"examples must be bounded to {MAX_EXAMPLES}, got {len(self.examples)}"
            )
        if self.cause is None:
            # Always a cause: the line that decided to refuse, when nothing was raised.
            object.__setattr__(self, "cause", Cause.here())
        elif not isinstance(self.cause, Cause):
            raise TypeError(f"{self.code}: cause must be a Cause, got {type(self.cause).__name__}")

    def as_dict(self) -> dict[str, object]:
        """The one failure entry every envelope carries, in the one key order.

        `VqaprError.as_dict`, `InputError`, `SimulationFailure` and `check` all emit this entry
        through this method; nothing else spells the keys (record `170`).
        """
        assert self.cause is not None
        return {
            "code": self.code,
            "status": int(self.status),
            "source": self.source.as_dict(),
            "requirement": self.requirement,
            "observed": self.observed,
            "fix": self.fix,
            "cause": self.cause.as_dict(),
            "examples": list(self.examples),
            "example_total": self.example_total,
        }

    @classmethod
    def bounded(
        cls,
        code: str,
        requirement: str,
        *,
        status: Status,
        fix: str,
        source: FailureSource | None = None,
        observed: str | None = None,
        cause: BaseException | Cause | None = None,
        examples: Sequence[str] = (),
        example_total: int | None = None,
    ) -> Failure:
        """예시를 상한까지 잘라 만든다. 호출자가 자르는 것을 잊지 않게 하려는 것.

        `cause` may be the exception itself; it is read into a `Cause` here so a raise site
        writes `cause=error` and nothing more. Omitted, the cause is this call's own raise site.
        """
        kept = tuple(str(e) for e in examples[:MAX_EXAMPLES])
        total = example_total if example_total is not None else len(examples)
        if isinstance(cause, BaseException):
            cause = Cause.of(cause)
        return cls(
            code=code,
            status=status,
            requirement=requirement,
            fix=fix,
            source=source if source is not None else FailureSource(),
            observed=observed,
            cause=cause if cause is not None else Cause.here(),
            examples=kept,
            example_total=total,
        )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """한 operation이 끝난 자리에서 모인 결과.

    `failures`가 비어 있으면 통과다. 비어 있지 않으면 `raise_if_failed()`가 던진다.
    """

    stage: Stage
    failures: tuple[Failure, ...] = ()
    mutation: bool = False
    retry_precondition: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_if_failed(self) -> None:
        if self.failures:
            raise VqaprError(
                stage=self.stage,
                failures=self.failures,
                mutation=self.mutation,
                retry_precondition=self.retry_precondition,
            )


class VqaprError(Exception):
    """package가 내는 모든 실패의 뿌리.

    `mutation`이 왜 지금부터 있나: 등록에서는 언제나 False라 쓸모없어 보이지만, commit 이후에
    실패할 수 있는 단계가 생겼을 때 뒤늦게 붙이면 그것 없이 짜인 호출부를 전부 고쳐야 한다.
    """

    def __init__(
        self,
        *,
        stage: Stage,
        failures: Sequence[Failure],
        mutation: bool = False,
        retry_precondition: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if not isinstance(stage, Stage):
            raise TypeError(f"stage must be a Stage, got {type(stage).__name__}")
        self.stage = stage
        self.failures: tuple[Failure, ...] = tuple(failures)
        self.mutation = mutation
        self.retry_precondition = retry_precondition
        self.correlation_id = correlation_id or uuid.uuid4().hex
        super().__init__(self._summary())

    def __reduce__(self) -> tuple[object, ...]:
        """Rebuild through the keyword-only constructor, so the error crosses a process boundary.

        The default pickling of an exception calls `cls(*args)` with the message, which this
        constructor refuses; a `--jobs` worker's refusal then came back to the parent as
        `TypeError: ... takes 1 positional argument` and rendered as unhandled with no failures
        (`docs/issues/archive/073`; record `170`).
        """
        return (
            _rebuild_error,
            (
                type(self),
                self.stage,
                self.failures,
                self.mutation,
                self.retry_precondition,
                self.correlation_id,
            ),
        )

    @property
    def status(self) -> Status:
        """The most severe status among the failures: 5xx before 4xx, then by number."""
        return max((f.status for f in self.failures), default=Status.INTERNAL)

    def _summary(self) -> str:
        head = f"{self.stage}: {len(self.failures)} failure(s)"
        return head + "".join(
            f"\n  [{int(f.status)} {f.code}] {f.requirement}" for f in self.failures
        )

    def as_dict(self) -> dict[str, object]:
        """agent가 읽는 형태. 사람이 읽는 것은 `str(err)`."""
        return {
            "stage": str(self.stage),
            "mutation": self.mutation,
            "retry_precondition": self.retry_precondition,
            "correlation_id": self.correlation_id,
            "failures": [f.as_dict() for f in self.failures],
        }


def _rebuild_error(
    cls: type[VqaprError],
    stage: Stage,
    failures: tuple[Failure, ...],
    mutation: bool,
    retry_precondition: str | None,
    correlation_id: str,
) -> VqaprError:
    """The unpickling half of `VqaprError.__reduce__`: the same error, same correlation id."""
    return cls(
        stage=stage,
        failures=failures,
        mutation=mutation,
        retry_precondition=retry_precondition,
        correlation_id=correlation_id,
    )


def unhandled(error: BaseException, *, stage: Stage) -> Failure:
    """The one failure for an exception nobody classified: 500 or 502 by whose frame raised it.

    The old envelope rendered these as `stage: "unhandled"` with an empty failure list and a
    traceback that was cut at eight lines or sent to a file. An agent could not tell the
    framework's bug from its own (`docs/issues/archive/076`). Now it is a failure like any other, with
    the whole traceback in `cause` and the status saying whose it is.
    """
    status = status_of(error)
    cause = Cause.of(error)
    if status is Status.CRASHED:
        fix = f"read the traceback in `cause`; the innermost frame is yours: {cause.where}"
    else:
        fix = (
            "this is not your submission's fault: file an issue upstream with the whole "
            "`cause` (type, message, traceback) and the command that produced it"
        )
    return Failure.bounded(
        "unhandled",
        "every failure is classified and named by the framework",
        status=status,
        observed=f"{type(error).__name__}: {error}",
        fix=fix,
        cause=cause,
    )


@dataclass(frozen=True, slots=True)
class _Collector:
    """단계 안에서 실패를 모은다. 하나 나왔다고 멈추지 않는다."""

    stage: Stage
    _found: list[Failure] = field(default_factory=list)

    def add(self, failure: Failure) -> None:
        self._found.append(failure)

    def done(self, *, mutation: bool = False, retry: str | None = None) -> Diagnosis:
        return Diagnosis(
            stage=self.stage,
            failures=tuple(self._found),
            mutation=mutation,
            retry_precondition=retry,
        )


def collector(stage: Stage) -> _Collector:
    return _Collector(stage=stage)
