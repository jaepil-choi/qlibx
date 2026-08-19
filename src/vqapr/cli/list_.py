"""`vqapr list <kind>` — read what the workspace already holds.

Workspace가 이미 복수형 accessor를 노출하므로 여기서 새 조회 코드를 만들지 않는다. 각 kind는
그 property 하나에 대응하고, 행 요약은 agent가 다음 명령의 인자로 쓸 식별자만 싣는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.workspace import Workspace

KINDS = (
    "datasets",
    "sources",
    "components",
    "agendas",
    "execution-inputs",
    "strategy-configs",
    "valuation-configs",
    "monitoring-policies",
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
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument(
        "--id",
        dest="identifier",
        default=None,
        help="substring filter applied to the declaration identity",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    workspace = Workspace.open(project_root)
    items = getattr(workspace, _ACCESSORS[args.kind])
    rows = [_summarize(item) for item in items]
    if args.identifier:
        needle = args.identifier
        rows = [row for row in rows if any(needle in value for value in row.values())]
    return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
