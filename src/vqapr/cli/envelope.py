"""The single JSON envelope every command returns.

첫 사용자가 agent이므로 성공과 실패가 **같은 모양**이어야 한다. 성공만 자유 텍스트면 agent는
성공/실패를 먼저 판별하고 분기해야 하지만, 대칭이면 파싱 경로가 하나다. 실패 본문은 이미
`VqaprError.as_dict()`와 `SimulationFailure.as_dict()`가 만들어 두었으므로 여기서 문구를 새로
만들지 않는다 — package는 판정만 하고 대화는 skill이 담당한다(PRD §2.6).

Record `171`: an exception nobody classified is no longer `stage: "unhandled"` with an empty
failure list and a traceback cut at eight lines. It is one real failure -- `code: "unhandled"`,
status 500 or 502 by whose frame raised it -- with the whole traceback in `cause`. Nothing is
truncated or moved out of the envelope: this is beta, and a reader deciding whether the fault is
theirs or the framework's needs all of it. The diagnostics file is still written as an extra.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from vqapr.domain.errors import Failure, Stage, Status, unhandled
from vqapr.inputs import BoundedRefusal
from vqapr.workspace import WORKSPACE_DIRECTORY

DIAGNOSTICS_DIRECTORY = "diagnostics"


def _dump(project_root: Path, correlation_id: str, text: str) -> str | None:
    """Write the traceback beside the workspace as well, or report that it could not be written.

    Rendering a failure must never fail. The envelope already carries the whole traceback in
    `cause`; this file is a convenience for a reader with a terminal, never a substitute, so a
    dump that cannot be written costs nothing but the `detail` key.
    """
    try:
        target = project_root / WORKSPACE_DIRECTORY / DIAGNOSTICS_DIRECTORY
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{correlation_id}.txt"
        path.write_text(text, encoding="utf-8")
    except OSError:
        return None
    return str(path)




class UsageError(BoundedRefusal):
    """명령줄 자체가 거부된 경우. package에는 도달하지 못했다.

    argparse는 기본적으로 stderr에 사람이 읽는 문구를 쓰고 `SystemExit`으로 나간다. 그러면 agent는
    stdout에서 아무것도 못 받고 exit code만 남으므로, "성공과 실패가 같은 모양"이라는 이 파일의
    계약이 바로 그 지점에서 깨진다. 그래서 usage 거부도 같은 봉투로 나간다.

    Stage `usage`, status 400 (record `171`): the submission -- the command line -- is wrong,
    and the operation under way was parsing it. Rendered through a real `Failure` like every
    other refusal; `docs/issues/030` (record `114`) ruled that the first refusal a new user ever
    sees is INSIDE the one documented shape, and now nothing spells that shape by hand.
    """

    def __init__(self, message: str, *, prog: str) -> None:
        self.message = message
        self.prog = prog
        super().__init__(message)

    def as_failure(self) -> Failure:
        return Failure.bounded(
            "usage.rejected",
            # argparse가 낸 문구를 그대로 싣는다. 여기서 새 문구를 만들면 package 판정과
            # 경쟁하는 두 번째 권위가 된다.
            self.message,
            status=Status.INVALID,
            observed=self.prog,
            fix=f"run `{self.prog} --help` to see the arguments this command accepts",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": str(Stage.USAGE),
            "mutation": False,
            "retry_precondition": None,
            "correlation_id": None,
            "failures": [self.as_failure().as_dict()],
        }


def success(stage: str, **fields: Any) -> dict[str, Any]:
    return {"ok": True, "stage": stage, **fields}


def failure(
    error: BaseException, *, project_root: Path | None = None, stage: Stage
) -> dict[str, Any]:
    """Render any exception as the agent-readable envelope.

    ``as_dict()`` 를 가진 package 실패는 그 본문을 그대로 쓴다. 그 외 예외는 `unhandled` 실패
    하나로 실린다: status 500(프레임워크 프레임이 맨 안쪽) 또는 502(사용자 파일이 맨 안쪽), 그리고
    `cause`에 traceback 전문. `stage`는 호출한 명령이 하던 일이다 -- 예외 자신은 모르지만 명령은
    안다.
    """
    if isinstance(error, BoundedRefusal):
        # 본문이 이미 유계다. argparse 내부 프레임이나 chained OSError 프레임은 증거가 아니라
        # 잡음이고, 증거는 사용자가 친 명령줄과 그가 준 경로 그 자체다.
        return {"ok": False, **error.as_dict(), "error": f"{type(error).__name__}: {error}"}

    body = getattr(error, "as_dict", None)
    if callable(body):
        # A classified refusal: its failures already carry their causes. No file is written
        # for it -- a read-only verb refusing must not create `.vqapr/` as a side effect.
        return {"ok": False, **body(), "error": f"{type(error).__name__}: {error}"}

    payload: dict[str, Any] = {
        "ok": False,
        "stage": str(stage),
        "mutation": False,
        "retry_precondition": None,
        "correlation_id": None,
        "failures": [unhandled(error, stage=stage).as_dict()],
        "error": f"{type(error).__name__}: {error}",
    }
    if project_root is not None:
        # The same traceback `cause` already carries, as a file for a reader with a terminal.
        # An extra, never a substitute: the envelope is whole without it.
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        detail = _dump(Path(project_root), "unhandled", text)
        if detail is not None:
            payload["detail"] = detail
    return payload


def note(text: str) -> None:
    """Write one advisory line to stderr, as UTF-8 bytes.

    Beside `emit` rather than in the caller, for the same reason `emit` writes bytes: a legacy code
    page (cp949 on a Korean Windows console) cannot encode a path that runs through a non-ASCII
    profile name, and an advisory that raises `UnicodeEncodeError` would take the command down
    with it -- worse than the staleness it was reporting.

    stderr, never stdout. stdout carries exactly one JSON document per command, and an agent
    having a single parsing path is that envelope's whole reason to exist.
    """
    stream = getattr(sys.stderr, "buffer", None)
    if stream is None:
        print(text, file=sys.stderr)
        return
    stream.write(text.encode("utf-8") + b"\n")
    stream.flush()


def emit(payload: dict[str, Any]) -> int:
    """Write one line of JSON and return the process exit code.

    The envelope is written as UTF-8 bytes rather than through the inherited console encoding.
    A legacy code page (cp949 on a Korean Windows console) cannot encode characters that appear
    in ordinary failure text, and losing the report to the reporting step is not acceptable.
    """
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(line)
    else:
        stream.write(line.encode("utf-8") + b"\n")
        stream.flush()
    return 0 if payload.get("ok") else 1
