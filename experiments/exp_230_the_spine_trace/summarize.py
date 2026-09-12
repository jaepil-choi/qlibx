"""Read a trace `trace.py` wrote and print what a stepper frame needs: the spine, in order.

    M="uv run python experiments/exp_230_the_spine_trace/summarize.py"
    $M TRACE.json                                         # overview
    $M TRACE.json --grep 'MarketClock|RunLoop' --limit 80  # the spine, filtered
    $M TRACE.json --around 1234 --width 8                 # one call's neighbours
    $M TRACE.json --top 25                                # cumulative ms by qualname

`--grep` lists every call whose `qualname` or file matches the regex, with its index, depth,
definition line and milliseconds -- the numbers a frame quotes. `--around IDX` shows the calls
before and after one index, indented by depth, which is how a frame's neighbours are found.
`--top` ranks qualnames by cumulative milliseconds and call count.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def overview(trace: dict) -> None:
    calls = trace["calls"]
    print(f"argv: {' '.join(trace['argv'])}")
    print(f"exit {trace['exit']} · {len(calls)} calls · {trace['elapsed_ms']} ms")
    envelope = trace.get("envelope")
    if isinstance(envelope, dict):
        keys = ", ".join(sorted(envelope))
        print(f"envelope: ok={envelope.get('ok')} stage={envelope.get('stage')} keys=[{keys}]")
    files = trace.get("files_after") or []
    print(f"files after: {len(files)}")
    for name in files:
        if ".vqapr" in name:
            print("   ", name)


def top(trace: dict, limit: int) -> None:
    total: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    where: dict[str, str] = {}
    for call in trace["calls"]:
        key = call["qualname"]
        total[key] += call["ms"] or 0.0
        count[key] += 1
        where.setdefault(key, f"{call['file']}:{call['line']}")
    ranked = sorted(total, key=lambda key: -total[key])[:limit]
    print(f"{'cumulative ms':>14}  {'calls':>6}  qualname  (file:line)")
    for key in ranked:
        print(f"{total[key]:>14.1f}  {count[key]:>6}  {key}  ({where[key]})")


NOISE = re.compile(r"<genexpr>|<lambda>|<listcomp>|<dictcomp>|<setcomp>")


def grep(
    trace: dict, pattern: str, limit: int, *, maxdepth: int | None = None, noise: bool = False
) -> None:
    regex = re.compile(pattern)
    shown = 0
    for call in trace["calls"]:
        if maxdepth is not None and call["depth"] > maxdepth:
            continue
        if not noise and NOISE.search(call["qualname"]):
            continue
        if regex.search(call["qualname"]) or regex.search(call["file"]):
            locals_ = " ".join(f"{k}={v}" for k, v in call.get("locals", {}).items())
            ms = call["ms"] if call["ms"] is not None else "?"
            print(
                f"#{call['idx']:<6} d{call['depth']:<3} {ms:>9} ms  "
                f"{call['file']}:{call['line']}  {call['qualname']}"
                + (f"  [{locals_}]" if locals_ else "")
                + ("  (author)" if call.get("author") else "")
            )
            shown += 1
            if shown >= limit:
                print(f"... (limit {limit})")
                break


def around(trace: dict, idx: int, width: int) -> None:
    calls = trace["calls"]
    for call in calls[max(0, idx - width) : idx + width + 1]:
        marker = ">>" if call["idx"] == idx else "  "
        indent = "  " * max(0, call["depth"] - 1)
        print(
            f"{marker} #{call['idx']:<6} {call['ms'] if call['ms'] is not None else '?':>8} ms  "
            f"{indent}{call['qualname']}  {call['file']}:{call['line']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=Path)
    parser.add_argument("--grep")
    parser.add_argument("--around", type=int)
    parser.add_argument("--width", type=int, default=10)
    parser.add_argument("--top", type=int)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--maxdepth", type=int)
    parser.add_argument(
        "--noise", action="store_true", help="keep genexpr/lambda/comprehension frames"
    )
    args = parser.parse_args()
    data = load(args.trace)
    if args.grep:
        grep(data, args.grep, args.limit, maxdepth=args.maxdepth, noise=args.noise)
    elif args.around is not None:
        around(data, args.around, args.width)
    elif args.top:
        top(data, args.top)
    else:
        overview(data)
