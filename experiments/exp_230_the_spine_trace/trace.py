"""Trace one CLI command with `sys.setprofile`, in this process, and write what happened.

The spine stepper (`docs/walkthroughs/*-spine-stepper-*.html`) is built from these traces, not
from imagination: every frame it shows carries the call index, the definition line and the
milliseconds this recorded. Run one command per process so the indices restart at zero:

    uv run python experiments/exp_230_the_spine_trace/trace.py OUT.json [--project DIR] -- \
        --project-root DIR register decl.yaml

What is recorded, per call into `src/vqapr` or the project's own components: `idx` (the n-th
call of the process), `depth`, `file:line` of the definition, the qualified name, `ms` from the
profiler's clock (inflated by the profiler itself; compare within a trace only), and for a few
named locals a short repr at call time. The command's JSON envelope and the exit code are kept
beside the calls, and so is the project directory's file list after the command.
"""

from __future__ import annotations

import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = str(REPO / "src" / "vqapr")
INTERESTING_LOCALS = (
    "argv",
    "event",
    "instant",
    "occurrence",
    "pending",
    "at",
    "cutoff",
    "target_at",
    "table_id",
    "run_id",
    "chunk",
    "rows",
    "stage",
    "kind",
    "layer",
    "member_kind",
)


def _short(value: object, limit: int = 140) -> str:
    try:
        text = repr(value)
    except Exception as error:
        text = f"<repr failed: {type(error).__name__}>"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def trace(argv: list[str], out: Path, project: Path | None) -> int:
    from vqapr.cli.main import main

    calls: list[dict[str, object]] = []
    open_frames: dict[int, tuple[int, float]] = {}
    counter = 0
    depth = 0
    project_str = str(project.resolve()) if project else None

    def profiler(frame, event, arg):
        nonlocal counter, depth
        code = frame.f_code
        filename = code.co_filename
        ours = filename.startswith(SRC) or (
            project_str is not None and filename.startswith(project_str)
        )
        if event == "call":
            depth += 1
            if not ours:
                return
            idx = counter
            counter += 1
            locals_seen = {
                name: _short(frame.f_locals[name])
                for name in INTERESTING_LOCALS
                if name in frame.f_locals
            }
            entry: dict[str, object] = {
                "idx": idx,
                "depth": depth,
                "file": str(Path(filename).relative_to(REPO)).replace("\\", "/")
                if filename.startswith(str(REPO))
                else filename,
                "line": code.co_firstlineno,
                "qualname": getattr(code, "co_qualname", code.co_name),
                "ms": None,
                "locals": locals_seen,
                "author": project_str is not None and filename.startswith(project_str),
            }
            calls.append(entry)
            open_frames[id(frame)] = (len(calls) - 1, time.perf_counter())
        elif event == "return":
            depth -= 1
            started = open_frames.pop(id(frame), None)
            if started is not None:
                position, t0 = started
                calls[position]["ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return None

    buffer = io.StringIO()
    started = time.perf_counter()
    sys.setprofile(profiler)
    try:
        with redirect_stdout(buffer):
            code = main(argv)
    finally:
        sys.setprofile(None)
    elapsed = time.perf_counter() - started
    printed = buffer.getvalue().strip().splitlines()
    envelope: object = None
    if printed:
        try:
            envelope = json.loads(printed[-1])
        except json.JSONDecodeError:
            envelope = printed[-1]
    files: list[str] = []
    if project is not None and project.exists():
        for path in sorted(project.rglob("*")):
            if path.is_file() and ".venv" not in path.parts and "__pycache__" not in path.parts:
                files.append(str(path.relative_to(project)).replace("\\", "/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "argv": argv,
                "exit": code,
                "elapsed_ms": round(elapsed * 1000, 1),
                "calls": calls,
                "envelope": envelope,
                "files_after": files,
            },
            ensure_ascii=False,
            indent=None,
        ),
        encoding="utf-8",
    )
    print(f"{out.name}: exit {code}, {len(calls)} calls, {elapsed * 1000:.0f} ms", file=sys.stderr)
    return code


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--" not in arguments or len(arguments) < 2:
        raise SystemExit("usage: trace.py OUT.json [--project DIR] -- <vqapr argv...>")
    split = arguments.index("--")
    head, tail = arguments[:split], arguments[split + 1 :]
    out_path = Path(head[0])
    project_dir = Path(head[head.index("--project") + 1]) if "--project" in head else None
    raise SystemExit(trace(tail, out_path, project_dir))
