"""`vqapr declare <file.yaml>` — the workspace declarations that are not components.

`register` takes a *component*: source on disk, an object inside it, a fingerprint over both.
The seven things declared here have none of that. A dataset is a projection over a file, an
agenda is a list of instants, a strategy config is a pair of identifiers. Forcing them through
`register` would give one verb two meanings — "fingerprint this code" and "write down this fact"
— and the second has no code to fingerprint.

Before this command they had **no CLI path at all**. `tests/cli/test_commands.py` proved it: its
`_workspace_for_run` fixture reached past the CLI into the library to build every one of them,
under a docstring that said *"everything `run` needs that the CLI itself cannot register"*. A user
who typed only `vqapr` commands could not reach a runnable workspace, and since an execution input
became mandatory for every run there was no way to reach one at all.

**One file, not seven commands.** These declarations reference each other — a strategy config
names an agenda, an execution input carries a source, an agenda can take its sessions from a
dataset — and declaring them separately means discovering the ordering by failing. One document is
also the artefact a user keeps: a workspace is reproducible by re-running one file, which is the
same reason `run` takes a spec rather than twenty flags.

Every key is optional. A document declaring only `agendas:` declares agendas, so the file grows
with the workspace instead of demanding everything on the first command.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import yaml

from vqapr.cli.envelope import success
from vqapr.public import (
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    MonitoringPolicy,
    OperationAgenda,
    OperationRole,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    Workspace,
    register_agenda,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
)

_SECTIONS = (
    "datasets",
    "execution_inputs",
    "agendas",
    "strategy_configs",
    "valuation_configs",
    "monitoring_policies",
)
"""Every section this command understands, in declaration order.

The order is a dependency order, not a preference: an agenda may read a dataset's sessions, and a
strategy config names an agenda that must already exist. Declaring them in file order instead
would make a valid document fail because of how the user happened to type it.
"""


def _mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping")
    return value


def _time(value: object, *, name: str) -> time:
    """Accept `"15:30"` and the `datetime.time` PyYAML may already have parsed."""
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a local time such as '15:30'")
    return time.fromisoformat(value)


def _source(declared: dict[str, Any], *, name: str) -> SourceSpec:
    return SourceSpec.of(
        str(declared["source_id"]),
        Path(str(declared["path"])),
        hive_partitioned=bool(declared.get("hive_partitioned", False)),
    )


def _dataset(dataset_id: str, declared: dict[str, Any]) -> tuple[DatasetRegistration, SourceSpec]:
    """A dataset and its source register together, so one declaration covers both.

    `workspace.register_dataset(registration, source)` takes them as a pair because a projection
    without the file it projects is not usable. Splitting them into two sections would let a
    document declare half of one.
    """
    body = _mapping(declared, name=f"datasets.{dataset_id}")
    return (
        DatasetRegistration.of(
            dataset_id,
            str(body["source_id"]),
            instrument_field=str(body["instrument_field"]),
            available_at=str(body["available_at"]),
            key_fields=tuple(str(field) for field in body["key_fields"]),
            fields={str(name): str(column) for name, column in body["fields"].items()},
        ),
        _source(body, name=f"datasets.{dataset_id}"),
    )


def _execution_input(input_id: str, declared: dict[str, Any]) -> ExecutionInputRegistration:
    body = _mapping(declared, name=f"execution_inputs.{input_id}")
    table = _mapping(body["table"], name=f"execution_inputs.{input_id}.table")
    fill = _mapping(body["fill"], name=f"execution_inputs.{input_id}.fill")
    return ExecutionInputRegistration.of(
        input_id,
        ExecutionTableSpec(
            source=_source(table, name=f"execution_inputs.{input_id}.table"),
            trade_at_field=str(table["trade_at_field"]),
            instrument_field=str(table["instrument_field"]),
            is_tradable_field=str(table["is_tradable_field"]),
            price_fields={str(name): str(column) for name, column in table["price_fields"].items()},
        ),
        FillConvention(
            FillSelector[str(fill["selector"]).upper()],
            _time(fill["at"], name=f"execution_inputs.{input_id}.fill.at"),
            str(fill["timezone"]),
            str(fill["trade_price"]),
        ),
    )


def _sessions(body: dict[str, Any], workspace: Workspace, *, name: str) -> list[datetime | date]:
    """Where an agenda's days come from: a dataset it follows, or an explicit list.

    `from_dataset` is the common case and the one worth making short. A cadence usually follows
    the data it reads, and `Workspace.evaluation_times` already knows those days exactly, so
    restating them by hand in the file is a chance to disagree with the dataset for no benefit.
    """
    dataset_id = body.get("from_dataset")
    declared = body.get("sessions")
    if (dataset_id is None) == (declared is None):
        raise ValueError(f"{name} must declare exactly one of from_dataset or sessions")
    if dataset_id is not None:
        return list(workspace.evaluation_times(str(dataset_id)))
    if not isinstance(declared, list) or not declared:
        raise TypeError(f"{name}.sessions must be a non-empty list of dates")
    return [
        value if isinstance(value, (datetime, date)) else date.fromisoformat(str(value))
        for value in declared
    ]


def _agenda(
    agenda_id: str, declared: dict[str, Any], workspace: Workspace, *, role: OperationRole
) -> OperationAgenda:
    """Build one agenda through `daily()`, which owns the rules a hand-built one gets wrong.

    `OperationAgenda.daily` derives the occurrence id scheme, and the fold and offset, from the
    zone. A file that typed those constants itself would be correct until the venue observed DST.
    """
    name = f"agendas.{agenda_id}"
    body = _mapping(declared, name=name)
    return OperationAgenda.daily(
        agenda_id=agenda_id,
        role=role,
        sessions=_sessions(body, workspace, name=name),
        at=_time(body["at"], name=f"{name}.at"),
        timezone=str(body["timezone"]),
        provenance=str(body.get("provenance", f"vqapr declare: {agenda_id}")),
    )


def _role(value: object, *, name: str) -> OperationRole:
    try:
        return OperationRole[str(value).upper()]
    except KeyError:
        permitted = ", ".join(role.name.lower() for role in OperationRole)
        raise ValueError(f"{name}.role must be one of: {permitted}") from None


def declare(document: dict[str, Any], project_root: Path) -> dict[str, list[str]]:
    """Apply every section the document declares, in dependency order.

    Returns what was declared per section so the caller reports facts rather than a count.

    The workspace is opened **only when a section needs to read one**. `declare` is the first
    command a user types in an empty directory, and the registrars create the workspace on the
    way in; opening it up front made a valid first declaration fail with `workspace.open.missing`,
    which sends the user to fix a directory rather than their file.
    """
    unknown = sorted(set(document) - set(_SECTIONS))
    if unknown:
        raise ValueError(
            f"unknown section(s): {', '.join(unknown)}; "
            f"this command declares {', '.join(_SECTIONS)}"
        )
    opened: Workspace | None = None

    def workspace() -> Workspace:
        nonlocal opened
        if opened is None:
            opened = Workspace.open(project_root)
        return opened

    declared: dict[str, list[str]] = {}

    for dataset_id, body in _mapping(document.get("datasets") or {}, name="datasets").items():
        registration, source = _dataset(str(dataset_id), body)
        register_dataset(project_root, registration, source)
        declared.setdefault("datasets", []).append(str(dataset_id))

    for input_id, body in _mapping(
        document.get("execution_inputs") or {}, name="execution_inputs"
    ).items():
        register_execution_input(project_root, _execution_input(str(input_id), body))
        declared.setdefault("execution_inputs", []).append(str(input_id))

    for agenda_id, body in _mapping(document.get("agendas") or {}, name="agendas").items():
        name = f"agendas.{agenda_id}"
        role = _role(_mapping(body, name=name)["role"], name=name)
        register_agenda(project_root, _agenda(str(agenda_id), body, workspace(), role=role))
        declared.setdefault("agendas", []).append(str(agenda_id))

    for component_id, body in _mapping(
        document.get("strategy_configs") or {}, name="strategy_configs"
    ).items():
        config = _mapping(body, name=f"strategy_configs.{component_id}")
        register_strategy_config(
            project_root,
            StrategyConfig(
                workspace().component(str(component_id)),
                str(config["agenda_id"]),
                OperationRole.STRATEGY_CALLBACK,
            ),
        )
        declared.setdefault("strategy_configs", []).append(str(component_id))

    for config_id, body in _mapping(
        document.get("valuation_configs") or {}, name="valuation_configs"
    ).items():
        config = _mapping(body, name=f"valuation_configs.{config_id}")
        register_valuation_config(
            project_root, ValuationConfig(str(config["agenda_id"]), OperationRole.VALUATION)
        )
        declared.setdefault("valuation_configs", []).append(str(config_id))

    for policy_id, body in _mapping(
        document.get("monitoring_policies") or {}, name="monitoring_policies"
    ).items():
        policy = _mapping(body, name=f"monitoring_policies.{policy_id}")
        register_monitoring_policy(
            project_root, MonitoringPolicy(str(policy["agenda_id"]), OperationRole.MONITORING)
        )
        declared.setdefault("monitoring_policies", []).append(str(policy_id))

    return declared


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("declaration", type=Path)


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    document = yaml.safe_load(args.declaration.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("a declaration must be a YAML mapping")
    return success("workspace.declare", declared=declare(document, project_root))
