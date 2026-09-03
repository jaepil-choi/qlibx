"""`vqapr list <kind>` — read what the workspace already holds, and what the store recorded.

Workspace가 이미 복수형 accessor를 노출하므로 여기서 새 조회 코드를 만들지 않는다. 각 kind는
그 property 하나에 대응하고, 행 요약은 agent가 다음 명령의 인자로 쓸 식별자만 싣는다.

빈 디렉터리에서도 성공한다. "아직 아무것도 없다"는 것은 이 명령이 대답할 수 있는 질문이지
실패가 아니다 — 그리고 이것은 agent가 방향을 잡으려고 **가장 먼저** 치는 명령이므로, 여기서
거절하면 첫 명령이 실패로 시작한다.

**Two kinds read the record store rather than the document** (record `139`, design §4.3):
`runs` lists the REGISTERED runs and, beside each, which strategy records the store holds for it;
`strategies --run <id>` lists those records with the fields a reader filters on -- the strategy,
its fingerprint, whether its contract held, when it ran. Neither creates new I/O: a record was
always read whole and four fields kept.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.register import cli_kind
from vqapr.flow.run import RunDefinition
from vqapr.flow.run_records import datamodel_refs, read_strategy_record, strategy_refs
from vqapr.inputs import VALUE_INVALID, InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace

KINDS = (
    "datasets",
    "sources",
    "components",
    "execution-inputs",
    # The roster was registrable and unlistable: `list` covered eight kinds and not this one, so a
    # registered roster could not be inspected from the CLI at all.
    "instruments",
    "runs",
    "strategies",
)

_ACCESSORS = {
    "datasets": "datasets",
    "sources": "sources",
    "components": "components",
    "execution-inputs": "execution_inputs",
    "runs": "run_definitions",
}

_IDENTITY_FIELDS = (
    "dataset_id",
    "source_id",
    "component_id",
    "execution_input_id",
    "run_id",
)


def _summarize(item: object) -> dict[str, Any]:
    """Reduce one declaration to the fields an agent needs to act on it."""
    summary: dict[str, Any] = {}
    for field in _IDENTITY_FIELDS:
        value = getattr(item, field, None)
        if value is not None:
            summary[field] = str(value)
    for field in ("kind", "fingerprint", "object_name", "timezone"):
        value = getattr(item, field, None)
        if value is None:
            continue
        # `kind` is spelled the way `new` and `register` accept it. Reporting the domain enum's
        # value gave a reader `data_model`, which they cannot type at any verb.
        summary[field] = cli_kind(value) if field == "kind" else str(value)
    if isinstance(item, RunDefinition):
        summary["strategies"] = [entry.component_id for entry in item.strategies]
        summary["start"] = None if item.start is None else item.start.isoformat()
        summary["end"] = None if item.end is None else item.end.isoformat()
        summary["exchange"] = item.exchange
        summary["execution_input_id"] = item.execution_input_id
    if not summary:
        summary["repr"] = repr(item)
    return summary


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "kind",
        choices=KINDS,
        help="which kind of declaration to list",
    )
    parser.add_argument(
        "--id",
        dest="identifier",
        default=None,
        help="substring filter applied to the declaration identity",
    )
    parser.add_argument(
        "--store-root",
        dest="store_root",
        type=Path,
        default=None,
        help="where run records live, when they were written outside the workspace directory",
    )
    parser.add_argument(
        "--run",
        dest="run_id",
        default=None,
        help="`strategies` only: the run whose strategy records to list (required)",
    )
    parser.add_argument(
        "--strategy",
        dest="strategy",
        default=None,
        help="`strategies` only: keep records of this strategy id",
    )
    parser.add_argument(
        "--fingerprint",
        dest="fingerprint",
        default=None,
        help="`strategies` only: keep records whose fingerprint starts with this prefix",
    )
    parser.add_argument(
        "--failed-contract",
        dest="failed_contract",
        action="store_true",
        help="`strategies` only: keep records where some declared constraint did not hold",
    )
    parser.add_argument(
        "--since",
        dest="since",
        default=None,
        help="`strategies` only: keep records whose period ends at or after this instant",
    )


def _strategies(root: Path, run_id: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    """Every finished strategy record of one run, found by scanning, filtered on record fields."""
    since = _instant(getattr(args, "since", None), name="--since")
    rows: list[dict[str, Any]] = []
    for ref in strategy_refs(root, run_id):
        record = read_strategy_record(root, run_id, ref)
        contract = record.get("contract") or {}
        failed = [
            constraint
            for constraint, report in contract.items()
            if isinstance(report, dict) and report.get("ok") is False
        ]
        period = record.get("period") or {}
        row = {
            "run_id": run_id,
            "strategy_ref": ref,
            "strategy_id": record.get("strategy_id"),
            "fingerprint": record.get("fingerprint"),
            "account_version": (record.get("account") or {}).get("version"),
            "tables": sorted(record.get("tables") or {}),
            "period": period,
            "contract_failed": failed,
        }
        wanted = getattr(args, "strategy", None)
        if wanted and row["strategy_id"] != wanted:
            continue
        prefix = getattr(args, "fingerprint", None)
        if prefix and not str(row["fingerprint"] or "").startswith(prefix):
            continue
        if getattr(args, "failed_contract", False) and not failed:
            continue
        if since is not None:
            ended = _instant(period.get("end"), name="period.end")
            if ended is None or ended < since:
                continue
        rows.append(row)
    return rows


def _instant(value: object, *, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must be an ISO-8601 datetime with a UTC offset",
            observed=repr(value),
            retry=f"write {name} like 2024-01-02T00:00:00+09:00, then retry",
        ) from error
    if parsed.tzinfo is None:
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must include a UTC offset",
            observed=repr(value),
            retry=f"write {name} like 2024-01-02T00:00:00+09:00, then retry",
        )
    return parsed


def _instruments(project_root: Path) -> list[dict[str, Any]]:
    """The registered roster, as at most one row, or none when the project has no roster.

    A sidecar rather than a workspace section, so this does not go through `_ACCESSORS`: the
    pointer lives in `.vqapr/instruments.json` beside `workspace.yaml`. The per-category counts
    are best-effort: the digest and the declared tables are always reported, and `unreadable`
    says so when the tables could not be opened, rather than turning an orientation command
    into a failure.
    """
    if not (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists():
        return []
    pointer = Workspace.open(project_root).registered_instruments()
    if pointer is None:
        return []
    row: dict[str, Any] = {
        "digest": str(pointer["digest"]),
        "tables": {str(kind): str(path) for kind, path in sorted(dict(pointer["tables"]).items())},
    }
    from vqapr.domain.roster import build_roster
    from vqapr.domain.roster_export import read_roster_table

    try:
        roster = build_roster(
            {
                str(kind): read_roster_table(Path(str(path)))
                for kind, path in dict(pointer["tables"]).items()
            }
        )
    except Exception as unreadable:
        row["unreadable"] = str(unreadable)
        return [row]
    row["by_kind"] = roster.histogram
    row["instruments"] = sum(roster.histogram.values())
    return [row]


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    store_root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    if args.kind == "instruments":
        rows = _instruments(project_root)
        if args.identifier:
            rows = [row for row in rows if args.identifier in row["digest"]]
        return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
    if args.kind == "strategies":
        run_id = getattr(args, "run_id", None)
        if not run_id:
            raise InputError(
                VALUE_INVALID,
                requirement="`list strategies` names the run whose records to list",
                observed="no --run given",
                retry="run `vqapr list runs`, then `vqapr list strategies --run <run-id>`",
            )
        rows = _strategies(store_root, run_id, args)
        if args.identifier:
            rows = [row for row in rows if args.identifier in str(row["strategy_ref"])]
        return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
    if not (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists():
        # 없는 workspace는 빈 workspace다. 존재 여부만 보고 통과시키는 이유는, 손상된 workspace는
        # 계속 시끄럽게 실패해야 하기 때문이다 — `Workspace.open`을 넓게 catch하면 그 구분이
        # 사라지고 손상이 "항목 0개"로 조용히 보고된다.
        return success("workspace.list", kind=args.kind, count=0, items=[])
    workspace = Workspace.open(project_root)
    items = getattr(workspace, _ACCESSORS[args.kind])
    rows = [_summarize(item) for item in items]
    if args.kind == "runs":
        # Beside each registered run, the member records the store holds for it: what ran, by
        # `<id>@<fp8>`, so a reader sees which tweaks of which models have been tried. A run
        # holds one kind (record `148`), so one of the two lists is always empty.
        for row in rows:
            run_id = str(row["run_id"])
            row["recorded"] = [
                *strategy_refs(store_root, run_id),
                *datamodel_refs(store_root, run_id),
            ]
    if args.identifier:
        needle = args.identifier
        rows = [row for row in rows if any(needle in str(value) for value in row.values())]
    return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
