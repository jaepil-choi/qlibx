"""`vqapr list <kind>` — read what the workspace already holds.

Workspace가 이미 복수형 accessor를 노출하므로 여기서 새 조회 코드를 만들지 않는다. 각 kind는
그 property 하나에 대응하고, 행 요약은 agent가 다음 명령의 인자로 쓸 식별자만 싣는다.

빈 디렉터리에서도 성공한다. "아직 아무것도 없다"는 것은 이 명령이 대답할 수 있는 질문이지
실패가 아니다 — 그리고 이것은 agent가 방향을 잡으려고 **가장 먼저** 치는 명령이므로, 여기서
거절하면 첫 명령이 실패로 시작한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.flow.run_records import read_record, run_ids
from vqapr.workspace import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace

KINDS = (
    "datasets",
    "sources",
    "components",
    "agendas",
    "execution-inputs",
    "strategy-configs",
    "valuation-configs",
    "monitoring-policies",
    "runs",
)

_ACCESSORS = {
    "datasets": "datasets",
    "sources": "sources",
    "components": "components",
    "agendas": "agendas",
    "execution-inputs": "execution_inputs",
    "strategy-configs": "strategy_configs",
    "valuation-configs": "valuation_configs",
    "monitoring-policies": "monitoring_policies",
}

_IDENTITY_FIELDS = (
    "dataset_id",
    "source_id",
    "component_id",
    "agenda_id",
    "execution_input_id",
)


def _summarize(item: object) -> dict[str, Any]:
    """Reduce one declaration to the fields an agent needs to act on it."""
    summary: dict[str, Any] = {}
    component = getattr(item, "component", None)
    component_id = getattr(component, "component_id", None)
    if component_id is not None:
        # StrategyConfig owns a ComponentRef rather than duplicating its id. Omitting the nested
        # identity made `list strategy-configs --id <component>` return zero rows even though
        # `register` reports and keys that config by component id.
        summary["component_id"] = str(component_id)
    for field in _IDENTITY_FIELDS:
        value = getattr(item, field, None)
        if value is not None:
            summary[field] = str(value)
    for field in ("kind", "fingerprint", "object_name", "role", "timezone"):
        value = getattr(item, field, None)
        if value is not None:
            summary[field] = str(value)
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
        help="where run records live, when `runs` were written outside the workspace directory",
    )


def _runs(project_root: Path, store_root: Path | None) -> list[dict[str, Any]]:
    """Every finished run, found by scanning rather than read from an index.

    An index file would put every concurrent writer on one atomic-replace target, which is the
    lost-update the workspace lock exists for -- and it would serialise exactly the thing five
    parallel runs need not to be. Scanning has no shared target, so this is O(runs) on purpose.
    """
    root = store_root or project_root / WORKSPACE_DIRECTORY
    rows: list[dict[str, Any]] = []
    for run_id in run_ids(root):
        record = read_record(root, run_id)
        account = record.get("account") or {}
        rows.append(
            {
                "run_id": run_id,
                "account_version": account.get("version"),
                "tables": sorted(record.get("tables") or {}),
                "period": record.get("period"),
            }
        )
    return rows


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "runs":
        # Runs live under `store.root`, not in the workspace document, so this path does not open
        # the workspace at all. An uninitialised directory holds zero runs, which is an answer.
        rows = _runs(project_root, getattr(args, "store_root", None))
        if args.identifier:
            rows = [row for row in rows if args.identifier in str(row["run_id"])]
        return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
    if not (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists():
        # 없는 workspace는 빈 workspace다. 존재 여부만 보고 통과시키는 이유는, 손상된 workspace는
        # 계속 시끄럽게 실패해야 하기 때문이다 — `Workspace.open`을 넓게 catch하면 그 구분이
        # 사라지고 손상이 "항목 0개"로 조용히 보고된다.
        return success("workspace.list", kind=args.kind, count=0, items=[])
    workspace = Workspace.open(project_root)
    items = getattr(workspace, _ACCESSORS[args.kind])
    rows = [_summarize(item) for item in items]
    if args.identifier:
        needle = args.identifier
        rows = [row for row in rows if any(needle in value for value in row.values())]
    return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
