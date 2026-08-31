"""The single JSON envelope every command returns.

첫 사용자가 agent이므로 성공과 실패가 **같은 모양**이어야 한다. 성공만 자유 텍스트면 agent는
성공/실패를 먼저 판별하고 분기해야 하지만, 대칭이면 파싱 경로가 하나다. 실패 본문은 이미
`VqaprError.as_dict()`와 `SimulationFailure.as_dict()`가 만들어 두었으므로 여기서 문구를 새로
만들지 않는다 — package는 판정만 하고 대화는 skill이 담당한다(PRD §2.6).

stdout에는 **경계가 있는 것만** 싣는다. traceback처럼 입력에 비례해 길어지는 것은 dump 파일로
보내고 경로만 남긴다.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from vqapr.inputs import BoundedRefusal
from vqapr.workspace import WORKSPACE_DIRECTORY

DIAGNOSTICS_DIRECTORY = "diagnostics"
MAX_INLINE_TRACEBACK_LINES = 8
"""이 줄 수를 넘으면 traceback을 파일로 보낸다. 짧으면 파일을 만들지 않는다."""


def _dump(project_root: Path, correlation_id: str, text: str) -> str | None:
    """Write the unbounded body beside the workspace, or report that it could not be written.

    Rendering a failure must never fail. If the dump cannot be written the caller keeps the
    bounded envelope and inlines the body instead of losing the report entirely.
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

    `family`는 `None`이다. `FailureFamily`는 package 단계의 닫힌 집합인데(architecture §8.3) 이
    실패는 그 어느 단계에도 들어가지 않았다. 없는 단계를 골라 넣으면 agent가 잘못 분류한다.
    """

    def __init__(self, message: str, *, prog: str) -> None:
        self.message = message
        self.prog = prog
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": "cli.usage",
            "family": None,
            "mutation": False,
            "retry_precondition": None,
            "correlation_id": None,
            "failures": [
                {
                    "code": "cli.usage.rejected",
                    # argparse가 낸 문구를 그대로 싣는다. 여기서 새 문구를 만들면 package 판정과
                    # 경쟁하는 두 번째 권위가 된다.
                    "requirement": self.message,
                    "observed": self.prog,
                    # `docs/issues/030`, second half, settled by record `114`: this refusal used to
                    # carry three of the six fields `SKILL.md` guarantees, on THE FIRST REFUSAL A
                    # NEW USER EVER SEES. A guarantee with an unwritten exception at the most
                    # common entry point is not a guarantee, so the answer is that `cli.usage` is
                    # INSIDE it -- and the three missing keys are added rather than excused.
                    #
                    # `fix` is real and actionable, which is the field the document tells a reader
                    # to read first. `source` and `explain` are null because this failure has
                    # neither: argparse rejected the command line, so there is no file to point at
                    # and no package concept to explain. `SKILL.md` already says a `source` field
                    # may be null when the failure has no such location; this is that case.
                    "fix": f"run `{self.prog} --help` to see the arguments this command accepts",
                    "source": None,
                    "explain": None,
                    "examples": [],
                    "example_total": 0,
                }
            ],
        }


def success(stage: str, **fields: Any) -> dict[str, Any]:
    return {"ok": True, "stage": stage, **fields}


def failure(error: BaseException, *, project_root: Path | None = None) -> dict[str, Any]:
    """Render any exception as the agent-readable envelope.

    ``as_dict()`` 를 가진 package 실패는 그 본문을 그대로 쓴다. 그 외 예외는 stage를 알 수 없으므로
    ``unhandled`` 로 표시해 agent가 "framework가 거부한 것"과 "예상 못 한 것"을 구분할 수 있게 한다.
    """
    if isinstance(error, BoundedRefusal):
        # 본문이 이미 유계다. argparse 내부 프레임이나 chained OSError 프레임은 증거가 아니라
        # 잡음이고, 증거는 사용자가 친 명령줄과 그가 준 경로 그 자체다.
        return {"ok": False, **error.as_dict(), "error": f"{type(error).__name__}: {error}"}

    text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    oversized = len(text.splitlines()) > MAX_INLINE_TRACEBACK_LINES
    detail: str | None = None
    if oversized and project_root is not None:
        correlation_id = str(getattr(error, "correlation_id", "") or "unhandled")
        detail = _dump(Path(project_root), correlation_id, text)

    body = getattr(error, "as_dict", None)
    if callable(body):
        payload: dict[str, Any] = {"ok": False, **body()}
    else:
        payload = {
            "ok": False,
            "stage": "unhandled",
            "family": None,
            "mutation": False,
            "retry_precondition": None,
            "correlation_id": None,
            "failures": [],
        }
    payload["error"] = f"{type(error).__name__}: {error}"
    if detail is not None:
        payload["detail"] = detail
    elif oversized:
        # The body could not be written, so it rides inline rather than disappearing.
        payload["traceback"] = text
    return payload


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
