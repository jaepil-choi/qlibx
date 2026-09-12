"""Digest every run record the showcases leave, normalised so it can be compared across a refactor.

The two-clocks campaign changes the spine twice (Stages 2 and 4 of
`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`). What must not change while it does is
**what a run records**, and the only way to say that with evidence is to hold a baseline beside the
tree and compare.

**Two things vary between two identical runs and neither is the record's content.** Measured on
`show_005_enhanced_index` at `redesign/two-clocks`, running the pipeline twice: every parquet table
and every `run.json` was byte-identical, and `strategy.json` differed in exactly

    .timing.*            wall clock. Not reproducible and not meant to be
    .component.path      an absolute path into the project directory

So the digest drops `timing` wherever it appears and rewrites the repository root out of every
string. Everything else is compared.

**Tables are hashed logically, not byte for byte.** A parquet writer that changes its compression
or its metadata would otherwise read as a data change and bury the real one. The digest reads each
table, renders its rows in a stable order, and hashes that -- so a format change is invisible and a
row change is not. Schema and row count are kept beside the hash so a mismatch is readable without
opening the file.

Usage::

    uv run python scripts/showcase_record_digest.py                  # print the digest
    uv run python scripts/showcase_record_digest.py --write PATH     # save it
    uv run python scripts/showcase_record_digest.py --check PATH     # compare against a baseline

`--check` exits non-zero and names every difference. Run the showcases first; this script only
reads what they left. `--showcases PATH` digests another checkout's `showcases/` directory -- a
worktree compared against develop's own outputs.

Sixty-four-hex digests are masked everywhere (one-loop campaign, 2026-09-10): a run identity folds
the sources' paths, so the same declaration run from two checkouts writes two `run_id`s into
otherwise identical rows, and a baseline recorded in one checkout could never match the other.
What a component's fingerprint or a run's identity computes is pinned by its own tests; what this
digest pins is everything else the run wrote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

REPOSITORY = Path(__file__).resolve().parents[1]
SHOWCASES = REPOSITORY / "showcases"

DROPPED_KEYS = frozenset({"timing"})
"""Keys whose whole subtree is wall clock, dropped wherever they appear."""

ROOT_PLACEHOLDER = "<REPOSITORY>"
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
HEX_PLACEHOLDER = "<HEX64>"


def _normalise(value: Any, repository: Path = REPOSITORY) -> Any:
    """Drop wall-clock subtrees and rewrite the repository root out of every string."""
    if isinstance(value, dict):
        return {
            k: _normalise(v, repository) for k, v in sorted(value.items()) if k not in DROPPED_KEYS
        }
    if isinstance(value, list):
        return [_normalise(item, repository) for item in value]
    if isinstance(value, str):
        for spelling in (str(repository), str(repository).replace("\\", "/")):
            value = value.replace(spelling, ROOT_PLACEHOLDER)
        return HEX64.sub(HEX_PLACEHOLDER, value.replace("\\", "/"))
    return value


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _facts_entry(path: Path, repository: Path = REPOSITORY) -> dict[str, Any]:
    payload = _normalise(json.loads(path.read_text(encoding="utf-8")), repository)
    return {"kind": "facts", "digest": _digest(json.dumps(payload, sort_keys=True, indent=None))}


def _table_entry(path: Path) -> dict[str, Any]:
    table = pq.read_table(path)
    columns = [str(name) for name in table.column_names]
    rows = [
        HEX64.sub(HEX_PLACEHOLDER, "\t".join(f"{k}={v!r}" for k, v in sorted(row.items())))
        for row in table.to_pylist()
    ]
    return {
        "kind": "table",
        "rows": table.num_rows,
        "columns": columns,
        "digest": _digest("\n".join(sorted(rows))),
    }


def digest(showcases: Path = SHOWCASES) -> dict[str, dict[str, Any]]:
    """Every record file under every showcase's outputs, keyed by repository-relative path."""
    entries: dict[str, dict[str, Any]] = {}
    repository = showcases.resolve().parent
    for showcase in sorted(showcases.glob("show_*")):
        outputs = showcase / "outputs"
        if not outputs.is_dir():
            continue
        for path in sorted(outputs.rglob("*")):
            if not path.is_file() or ".vqapr" not in path.parts or "runs" not in path.parts:
                continue
            key = path.relative_to(repository).as_posix()
            if path.suffix == ".json":
                entries[key] = _facts_entry(path, repository)
            elif path.suffix == ".parquet":
                entries[key] = _table_entry(path)
    return entries


def _report(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    problems = []
    for key in sorted(set(baseline) - set(current)):
        problems.append(f"missing: {key}")
    for key in sorted(set(current) - set(baseline)):
        problems.append(f"unexpected: {key}")
    for key in sorted(set(baseline) & set(current)):
        was, now = baseline[key], current[key]
        if was == now:
            continue
        differing = sorted(k for k in set(was) | set(now) if was.get(k) != now.get(k))
        detail = ", ".join(f"{k}: {was.get(k)!r} -> {now.get(k)!r}" for k in differing)
        problems.append(f"changed: {key}\n    {detail}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", type=Path, help="save the digest to this path")
    group.add_argument("--check", type=Path, help="compare the digest against this baseline")
    parser.add_argument(
        "--showcases", type=Path, default=SHOWCASES, help="another checkout's showcases/ directory"
    )
    args = parser.parse_args(argv)

    current = digest(args.showcases)
    if not current:
        print("no showcase records found -- run the showcases first", file=sys.stderr)
        return 2

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
        args.write.write_text(payload, encoding="utf-8")
        print(f"wrote {len(current)} entries to {args.write}")
        return 0

    if args.check:
        baseline = json.loads(args.check.read_text(encoding="utf-8"))
        problems = _report(baseline, current)
        if problems:
            print(f"{len(problems)} difference(s) against {args.check}:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        print(f"{len(current)} entries match {args.check}")
        return 0

    print(json.dumps(current, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
