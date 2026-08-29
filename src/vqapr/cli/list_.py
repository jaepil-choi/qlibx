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
from vqapr.cli.register import cli_kind
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
    # The roster was registrable and unlistable: `list` covered eight kinds and not this one, so a
    # registered roster could not be inspected from the CLI at all. Both first-time-user journeys
    # ended up opening `.vqapr/instruments.json` by hand, which is a file this surface should
    # never require a reader to know about.
    "instruments",
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
        if value is None:
            continue
        # `kind` is spelled the way `new` and `register` accept it. Reporting the domain enum's
        # value gave a reader `data_model`, which they cannot type at any verb.
        summary[field] = cli_kind(value) if field == "kind" else str(value)
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


def _instruments(project_root: Path) -> list[dict[str, Any]]:
    """The registered roster, as at most one row, or none when the project has no roster.

    A sidecar rather than a workspace section, so this does not go through `_ACCESSORS`: the
    pointer lives in `.vqapr/instruments.json` beside `workspace.yaml` (see
    `Workspace.roster_path` for why it is not inside the document).

    The pointer stores `schema`, `tables` and `digest` and no counts, so the per-category numbers
    are read from the tables it points at. That read can fail for reasons that are not this
    command's business -- a table moved, a disk unmounted -- and `list` is the command an agent
    runs FIRST to orient itself. So the counts are best-effort: the digest and the declared tables
    are always reported, and `unreadable` says so when the tables could not be opened, rather than
    turning an orientation command into a failure.
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
    # Imported outside the try. They perform no I/O, so an ImportError from either is a packaging
    # defect and must fail loudly rather than be reported as `unreadable: No module named ...` on
    # a row that otherwise looks healthy -- a framework problem wearing a data-availability label.
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
    if args.kind == "instruments":
        # `count` is the number of rows, as it is for every other kind: a project holds one roster
        # or none. How many instruments it describes is `items[0]["instruments"]`, which is a
        # different question and gets its own field rather than overloading this one.
        rows = _instruments(project_root)
        if args.identifier:
            rows = [row for row in rows if args.identifier in row["digest"]]
        return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
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
