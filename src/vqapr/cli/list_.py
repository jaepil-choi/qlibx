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
from vqapr.domain.inputs import VALUE_INVALID, InputError
from vqapr.extension.component import ComponentKind
from vqapr.extension.loading import load_constraint, load_data_model, load_strategy_model
from vqapr.project.registration import AUTHORED_KINDS
from vqapr.project.run import RunDefinition
from vqapr.project.store import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace
from vqapr.record import (
    STATUS_COMPLETED,
    datamodel_progress,
    datamodel_refs,
    read_datamodel_record,
    read_strategy_record,
    recorded_run_ids,
    strategy_progress,
    strategy_refs,
    unfinished_datamodel_refs,
    unfinished_strategy_refs,
)

KINDS = (
    "datasets",
    "sources",
    "components",
    # The roster was registrable and unlistable: `list` covered eight kinds and not this one, so a
    # registered roster could not be inspected from the CLI at all.
    "instruments",
    "runs",
    "strategies",
    "datamodels",
)

COMPONENT_KINDS = (*AUTHORED_KINDS, "exchange")
"""What `--kind` accepts: the three kinds an author registers by name, plus the one declared.

Spelled the way `new` and `register` spell them and the way `list` reports them (`cli_kind`),
so the value a reader copies off one row filters the next call. `docs/issues/083` is a reader
handing `list components` to `show model` and breaking on the exchange because nothing could
say "the strategies and datamodels only".
"""

_ACCESSORS = {
    "datasets": "datasets",
    "sources": "sources",
    "components": "components",
    "runs": "run_definitions",
}

_IDENTITY_FIELDS = (
    "dataset_id",
    "source_id",
    "component_id",
    "run_id",
)


def _summarize(item: object) -> dict[str, Any]:
    """Reduce one declaration to the fields an agent needs to act on it."""
    summary: dict[str, Any] = {}
    for field in _IDENTITY_FIELDS:
        value = getattr(item, field, None)
        if value is not None:
            summary[field] = str(value)
    for field in ("kind", "fingerprint", "object_name", "timezone", "produced_by"):
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
        summary["execution"] = (
            None if item.execution is None else item.execution.model_dump(mode="json")
        )
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
        "--kind",
        dest="component_kind",
        choices=COMPONENT_KINDS,
        default=None,
        help="`components` only: keep components of this kind, spelled as `new` and `register` "
        "spell it",
    )
    parser.add_argument(
        "--reads",
        dest="reads",
        default=None,
        help=(
            "`components` only: keep the strategies, datamodels and constraints whose `inputs()` "
            "name this dataset id. Loads each component to ask it, in this one process"
        ),
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
        help="`strategies`/`datamodels`: the run whose member records to list (required)",
    )
    parser.add_argument(
        "--strategy",
        dest="strategy",
        default=None,
        help="`strategies`/`datamodels`: keep records of this model id",
    )
    parser.add_argument(
        "--fingerprint",
        dest="fingerprint",
        default=None,
        help="`strategies`/`datamodels`: keep records whose fingerprint starts with this prefix",
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
        help="`strategies`/`datamodels`: keep records whose period ends at or after this instant",
    )


def _strategies(root: Path, run_id: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    """Every strategy record of one run, finished or not, filtered on record fields.

    Finished records first, each `status: completed`. Then every strategy directory that has no
    record yet (`docs/issues/074`): `status: running` while its writer keeps touching its lock,
    with `chunks`, `last_event_time` and `lock.refreshed_ago` so a reader can see whether it is
    still advancing; `status: unfinished` once the lock is stale or gone, which is what a killed
    or refused strategy leaves. Those rows have no `fingerprint` beyond the `<fp8>` in their ref,
    no `period` and no contract, so `--failed-contract` never keeps them and `--since` reads their
    `last_event_time`.
    """
    since = _instant(getattr(args, "since", None), name="--since")
    wanted = getattr(args, "strategy", None)
    prefix = getattr(args, "fingerprint", None)
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
            "status": STATUS_COMPLETED,
            "account_version": (record.get("account") or {}).get("version"),
            "tables": sorted(record.get("tables") or {}),
            "period": period,
            "contract_failed": failed,
        }
        if wanted and row["strategy_id"] != wanted:
            continue
        if prefix and not str(row["fingerprint"] or "").startswith(prefix):
            continue
        if getattr(args, "failed_contract", False) and not failed:
            continue
        if since is not None:
            ended = _instant(period.get("end"), name="period.end")
            if ended is None or ended < since:
                continue
        rows.append(row)
    if getattr(args, "failed_contract", False):
        return rows
    for ref in unfinished_strategy_refs(root, run_id):
        strategy_id, _, fp8 = ref.rpartition("@")
        if wanted and strategy_id != wanted:
            continue
        if prefix and not fp8.startswith(prefix):
            continue
        progress = strategy_progress(root, run_id, ref)
        if since is not None:
            last = _instant(progress.get("last_event_time"), name="last_event_time")
            if last is None or last < since:
                continue
        rows.append(
            {
                "run_id": run_id,
                "strategy_ref": ref,
                "strategy_id": strategy_id,
                "fingerprint": None,
                **progress,
            }
        )
    return rows


def _datamodels(root: Path, run_id: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    """Every datamodel record of one run (record `148`), finished or not (`docs/issues/080`).

    Finished records first, `status: completed`. Then every datamodel directory without a
    record, the way `_strategies` lists them: `running` while its lock is fresh, `unfinished`
    once it is stale -- a datamodel run that died inside a callback, which used to leave a
    directory nothing listed and `rm datamodel` could not name.
    """
    since = _instant(getattr(args, "since", None), name="--since")
    rows: list[dict[str, Any]] = []
    for ref in datamodel_refs(root, run_id):
        record = read_datamodel_record(root, run_id, ref)
        period = record.get("period") or {}
        row = {
            "run_id": run_id,
            "datamodel_ref": ref,
            "datamodel_id": record.get("datamodel_id"),
            "fingerprint": record.get("fingerprint"),
            "dataset_id": record.get("dataset_id"),
            "rows": record.get("rows"),
            "status": STATUS_COMPLETED,
            "period": period,
        }
        wanted = getattr(args, "strategy", None)
        if wanted and row["datamodel_id"] != wanted:
            continue
        prefix = getattr(args, "fingerprint", None)
        if prefix and not str(row["fingerprint"] or "").startswith(prefix):
            continue
        if since is not None:
            ended = _instant(period.get("end"), name="period.end")
            if ended is None or ended < since:
                continue
        rows.append(row)
    wanted = getattr(args, "strategy", None)
    prefix = getattr(args, "fingerprint", None)
    for ref in unfinished_datamodel_refs(root, run_id):
        datamodel_id, _, fp8 = ref.rpartition("@")
        if wanted and datamodel_id != wanted:
            continue
        if prefix and not fp8.startswith(prefix):
            continue
        progress = datamodel_progress(root, run_id, ref)
        if since is not None:
            last = _instant(progress.get("last_event_time"), name="last_event_time")
            if last is None or last < since:
                continue
        rows.append(
            {
                "run_id": run_id,
                "datamodel_ref": ref,
                "datamodel_id": datamodel_id,
                "fingerprint": None,
                "dataset_id": None,
                "rows": None,
                **progress,
            }
        )
    return rows


def _reading(
    project_root: Path, workspace: Workspace, rows: list[dict[str, Any]], dataset_id: str
) -> list[dict[str, Any]]:
    """The components whose declared reads name `dataset_id`, and what each reads from it.

    The reverse of `show model` (`docs/issues/082`): "who reads this dataset" had no verb, so it
    was `list components` then `show model` per component -- 41 processes and 36 seconds on a
    forty-component workspace. The cost was the process starts, not the loads: this asks every
    component in this one process, the way `show model` asks one. An exchange declares no
    reads and is not asked.
    """
    loaders = {
        ComponentKind.STRATEGY_MODEL: load_strategy_model,
        ComponentKind.DATA_MODEL: load_data_model,
        ComponentKind.CONSTRAINT: load_constraint,
    }
    by_id = {str(ref.component_id): ref for ref in workspace.components}
    kept: list[dict[str, Any]] = []
    for row in rows:
        ref = by_id.get(str(row.get("component_id")))
        loader = None if ref is None else loaders.get(ref.kind)
        if loader is None:
            continue
        declared = loader(ref, project_root=project_root).inputs()
        fields = sorted(
            {
                field
                for declaration in declared.values()
                if str(declaration.dataset_id) == dataset_id
                for field in declaration.fields
            }
        )
        if fields:
            kept.append({**row, "reads": {dataset_id: fields}})
    return kept


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
    tables = pointer["tables"]
    if not isinstance(tables, dict):
        # `registered_instruments` refuses a pointer whose `tables` is not a JSON object.
        raise RuntimeError("registered_instruments admitted a roster pointer without tables")
    row: dict[str, Any] = {
        "digest": str(pointer["digest"]),
        "tables": {str(kind): str(path) for kind, path in sorted(tables.items())},
    }
    from vqapr.domain.instruments import build_roster, read_roster_table

    try:
        roster = build_roster(
            {str(kind): read_roster_table(Path(str(path))) for kind, path in tables.items()}
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
    if args.kind == "datamodels":
        run_id = getattr(args, "run_id", None)
        if not run_id:
            raise InputError(
                VALUE_INVALID,
                requirement="`list datamodels` names the run whose records to list",
                observed="no --run given",
                retry="run `vqapr list runs`, then `vqapr list datamodels --run <run-id>`",
            )
        rows = _datamodels(store_root, run_id, args)
        if args.identifier:
            rows = [row for row in rows if args.identifier in str(row["datamodel_ref"])]
        return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
    if not (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists():
        # 없는 workspace는 빈 workspace다. 존재 여부만 보고 통과시키는 이유는, 손상된 workspace는
        # 계속 시끄럽게 실패해야 하기 때문이다 — `Workspace.open`을 넓게 catch하면 그 구분이
        # 사라지고 손상이 "항목 0개"로 조용히 보고된다.
        return success("workspace.list", kind=args.kind, count=0, items=[])
    component_kind = getattr(args, "component_kind", None)
    if component_kind is not None and args.kind != "components":
        raise InputError(
            VALUE_INVALID,
            requirement="`--kind` filters `list components`",
            observed=f"--kind {component_kind!r} given with `list {args.kind}`",
            retry="run `vqapr list components --kind <kind>`",
        )
    workspace = Workspace.open(project_root)
    items = getattr(workspace, _ACCESSORS[args.kind])
    rows = [_summarize(item) for item in items]
    if component_kind is not None:
        rows = [row for row in rows if row.get("kind") == component_kind]
    reads = getattr(args, "reads", None)
    if reads is not None:
        if args.kind != "components":
            raise InputError(
                VALUE_INVALID,
                requirement="`--reads` filters `list components`",
                observed=f"--reads {reads!r} given with `list {args.kind}`",
                retry="run `vqapr list components --reads <dataset-id>`",
            )
        rows = _reading(project_root, workspace, rows, reads)
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
            row["status"] = "registered"
        # And every run the STORE holds that the workspace no longer registers
        # (`docs/issues/081`): withdrawing a definition left its records readable but not
        # findable, because this walked the registrations only. An orphan is an entry point to
        # `list strategies|datamodels --run` and to `rm run`, which is all that was missing.
        registered = {str(row["run_id"]) for row in rows}
        for run_id in recorded_run_ids(store_root):
            if run_id in registered:
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "status": "orphaned",
                    "definition": None,
                    "recorded": [
                        *strategy_refs(store_root, run_id),
                        *datamodel_refs(store_root, run_id),
                    ],
                    "unfinished": [
                        *unfinished_strategy_refs(store_root, run_id),
                        *unfinished_datamodel_refs(store_root, run_id),
                    ],
                }
            )
    if args.identifier:
        needle = args.identifier
        rows = [row for row in rows if any(needle in str(value) for value in row.values())]
    return success("workspace.list", kind=args.kind, count=len(rows), items=rows)
