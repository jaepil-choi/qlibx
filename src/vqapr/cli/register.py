"""`vqapr register <declaration.yaml>` — validate everything declared, then persist it.

**One verb, one file.** A workspace holds two kinds of thing: code the user wrote (a Strategy, a
DataModel, a Constraint, a venue) and facts about the world that code needs (where the data is,
what its columns mean, when decisions happen, at what price they fill). Both are registrations —
both are refused unless they check out, and both live in the same workspace — so both enter here.

`check` is not a separate command. Every path through this file validates before it writes, so a
registration that succeeds is one the framework can use, and nothing lands that cannot be run.

## Why a file and not flags

A component cannot be registered from argv alone without lying about what registration needs. A
DataModel needs the dataset it reads; a Strategy needs its cadence; a dataset needs its
`available_at` column, its logical key, and the field map that gives its columns framework names.
None of that fits a flag, and a command that accepted the component without them would register
something no run could use — the exact "registered but unusable" state this package refuses.

So the declaration is the unit. `vqapr new` emits one beside the component it scaffolds, and
`register` refuses a component that does not bring one.

## What is validated, not merely recorded

- **datasets** — every declared column exists, `available_at` is timezone-aware, and the logical
  key is scanned in full for nulls and duplicates. A dataset whose `(available_at, instrument)`
  repeats is refused with the offending groups as evidence, because a duplicated key silently
  changes what a lookback window contains.
- **execution inputs** — the same schema check over the venue table, plus the fill convention.
- **components** — loaded, constructed, and put through `conformance()`: every contract method
  Flow calls must exist and accept the positional call it makes.
- **configs** — the agenda and component they name must already be registered.

Sections are applied in dependency order, not file order, so a valid document cannot fail because
of how the user happened to type it.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import read_yaml_mapping
from vqapr.domain.errors import Failure, FailureFamily, collector
from vqapr.extension.component import ComponentKind
from vqapr.extension.registration import (
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)
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

_COMPONENT_KINDS = {
    "datamodel": (ComponentKind.DATA_MODEL, register_data_model),
    "strategy": (ComponentKind.STRATEGY_MODEL, register_strategy_model),
    "constraint": (ComponentKind.CONSTRAINT, register_constraint),
    "exchange": (ComponentKind.EXCHANGE, register_exchange),
}
"""확장점 넷 전부. canon §10.2가 닫아두지 말라고 한 목록이다.

무엇이 실제로 좁은 문인지는 `load_exchange`가 정한다 — shipped profile을 상속하지 않거나
`execute()`를 갈아치운 것은 거기서 거부된다. CLI가 kind 목록으로 막을 일이 아니다.
"""

DECLARE_STAGE = "declaration.read"
"""Reading the user's declaration document, before any workspace work begins.

Separate from `workspace.dataset.register` on purpose: that stage means the workspace refused a
well-formed declaration, while this one means the document itself is incomplete. Reporting the
second as the first sends a reader to inspect their workspace when the file on their disk is what
needs editing.
"""

SECTIONS = (
    "datasets",
    "execution_inputs",
    "agendas",
    "components",
    "strategy_configs",
    "valuation_configs",
    "monitoring_policies",
)
"""Every section this command understands, in dependency order.

The order is a dependency order, not a preference: an agenda may read a dataset's sessions, and a
strategy config names both a component and an agenda that must already exist. Applying them in
file order would make a valid document fail because of the order the user typed it in.
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


def _require_keys(body: dict[str, Any], keys: Sequence[str], *, name: str) -> None:
    """Name every key this declaration is missing, in one refusal.

    Raising on the first absent key costs one round trip per key: a reader fixes `fields`, re-runs,
    is told about `source_id`, re-runs, and learns the required set one exception at a time with no
    way to see it whole. Measured on a first-time reader, that pattern produced three failed
    attempts at the same command before they stopped.

    This is the same reason `Diagnosis` carries a tuple of `Failure` rather than one: an agent
    fixing its own declaration must receive the problems together.
    """
    missing = [key for key in keys if key not in body]
    if not missing:
        return
    found = collector(DECLARE_STAGE, FailureFamily.DATA)
    for key in missing:
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.key_missing",
                requirement=f"{name} must declare {key}",
                observed=f"{name} declares: {', '.join(sorted(body)) or '(nothing)'}",
            )
        )
    found.done().raise_if_failed()


def _required(body: dict[str, Any], key: str, *, name: str) -> Any:
    """Read a key that `_require_keys` has already proven present.

    The typed refusal is raised by `_require_keys` so that every missing key in a declaration is
    named at once. This still refuses rather than trusting the caller, because a builder reached
    through a path that forgot to pre-check must not read a `KeyError` into the envelope.
    """
    if key not in body:
        _require_keys(body, (key,), name=name)
    return body[key]


def _source(body: dict[str, Any], *, name: str, base: Path) -> SourceSpec:
    """A data path resolves against the declaration's directory when relative, as a component does.

    One rule for every path in the file. A document that resolved code one way and data another
    would be portable only by accident.
    """
    declared = Path(str(_required(body, "path", name=name)))
    return SourceSpec.of(
        str(_required(body, "source_id", name=name)),
        declared if declared.is_absolute() else base / declared,
        hive_partitioned=bool(body.get("hive_partitioned", False)),
    )


_DATASET_KEYS = (
    "source_id",
    "path",
    "instrument_field",
    "available_at",
    "key_fields",
    "fields",
)
"""Every key a dataset declaration must carry.

This tuple is used twice: once to pre-check the full set so that every missing key is named in a
single refusal, and once by `_required` as a fallback guard. The pre-check is why Agent A's
two-blocker run should not recur: where it previously took three round trips to discover five keys
one at a time, a single refusal now names all of them.

`source_id` and `path` live inline under the dataset because a dataset and its physical file
register together — `register_dataset(registration, source)` takes them as a pair. There is no
separate `sources:` section; the error that formerly said just ``must declare source_id`` without
saying where a source goes was the direct cause of FRICTION F-007.
"""


def _dataset(
    dataset_id: str, declared: object, *, base: Path
) -> tuple[DatasetRegistration, SourceSpec]:
    """A dataset and its source register together, so one declaration covers both.

    `register_dataset(registration, source)` takes them as a pair because a projection without the
    file it projects is not usable. A separate `sources:` section would let a document declare
    half of one.
    """
    name = f"datasets.{dataset_id}"
    body = _mapping(declared, name=name)
    _require_keys(body, _DATASET_KEYS, name=name)
    fields = _mapping(_required(body, "fields", name=name), name=f"{name}.fields")
    return (
        DatasetRegistration.of(
            dataset_id,
            str(_required(body, "source_id", name=name)),
            instrument_field=str(_required(body, "instrument_field", name=name)),
            available_at=str(_required(body, "available_at", name=name)),
            key_fields=tuple(str(field) for field in _required(body, "key_fields", name=name)),
            fields={str(key): str(column) for key, column in fields.items()},
        ),
        _source(body, name=name, base=base),
    )


def _execution_input(input_id: str, declared: object, *, base: Path) -> ExecutionInputRegistration:
    name = f"execution_inputs.{input_id}"
    body = _mapping(declared, name=name)
    table = _mapping(_required(body, "table", name=name), name=f"{name}.table")
    fill = _mapping(_required(body, "fill", name=name), name=f"{name}.fill")
    prices = _mapping(_required(table, "price_fields", name=f"{name}.table"), name=f"{name}.table")
    return ExecutionInputRegistration.of(
        input_id,
        ExecutionTableSpec(
            source=_source(table, name=f"{name}.table", base=base),
            trade_at_field=str(_required(table, "trade_at_field", name=f"{name}.table")),
            instrument_field=str(_required(table, "instrument_field", name=f"{name}.table")),
            is_tradable_field=str(_required(table, "is_tradable_field", name=f"{name}.table")),
            price_fields={str(key): str(column) for key, column in prices.items()},
        ),
        FillConvention(
            FillSelector[str(_required(fill, "selector", name=f"{name}.fill")).upper()],
            _time(_required(fill, "at", name=f"{name}.fill"), name=f"{name}.fill.at"),
            str(_required(fill, "timezone", name=f"{name}.fill")),
            str(_required(fill, "trade_price", name=f"{name}.fill")),
        ),
    )


def _sessions(body: dict[str, Any], workspace: Workspace, *, name: str) -> list[datetime | date]:
    """Where an agenda's days come from: a dataset it follows, or an explicit list.

    `from_dataset` is the common case and the one worth making short. A cadence usually follows
    the data it reads, and `Workspace.evaluation_times` already knows those days exactly, so
    restating them by hand is a chance to disagree with the dataset for no benefit.
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


def _role(value: object, *, name: str) -> OperationRole:
    try:
        return OperationRole[str(value).upper()]
    except KeyError:
        permitted = ", ".join(role.name.lower() for role in OperationRole)
        raise ValueError(f"{name}.role must be one of: {permitted}") from None


def _agenda(agenda_id: str, declared: object, workspace: Workspace) -> OperationAgenda:
    """Build one agenda through `daily()`, which owns the rules a hand-built one gets wrong.

    `OperationAgenda.daily` derives the occurrence id scheme, the fold, and the offset from the
    zone. A file that typed those constants itself would be correct until the venue observed DST.
    """
    name = f"agendas.{agenda_id}"
    body = _mapping(declared, name=name)
    return OperationAgenda.daily(
        agenda_id=agenda_id,
        role=_role(_required(body, "role", name=name), name=name),
        sessions=_sessions(body, workspace, name=name),
        at=_time(_required(body, "at", name=name), name=f"{name}.at"),
        timezone=str(_required(body, "timezone", name=name)),
        provenance=str(body.get("provenance", f"vqapr register: {agenda_id}")),
    )


def _component(component_id: str, declared: object, project_root: Path, *, base: Path) -> str:
    """Register one authored component through the door its kind declares.

    A relative path resolves against the **declaration's own directory**, not the process working
    directory, so a document sits beside the component it declares and stays portable. `vqapr new`
    emits exactly that shape: `path: my_alpha.py` next to `my_alpha.py`.
    """
    name = f"components.{component_id}"
    body = _mapping(declared, name=name)
    raw_kind = str(_required(body, "kind", name=name))
    if raw_kind not in _COMPONENT_KINDS:
        permitted = ", ".join(_COMPONENT_KINDS)
        raise ValueError(f"{name}.kind must be one of: {permitted}")
    _, register = _COMPONENT_KINDS[raw_kind]
    config = body.get("config")
    if config is not None and not isinstance(config, dict):
        raise TypeError(f"{name}.config must be a mapping")
    declared_path = Path(str(_required(body, "path", name=name)))
    ref = register(
        project_root,
        component_id,
        declared_path if declared_path.is_absolute() else base / declared_path,
        str(_required(body, "object_name", name=name)),
        config=config,
    )
    return str(ref.component_id)


def apply(document: dict[str, Any], project_root: Path, *, base: Path) -> dict[str, list[str]]:
    """Apply every section the document declares, in dependency order.

    Returns what was registered per section, so the reply states facts rather than a count.

    The workspace is opened **only when a section needs to read one**. `register` is the first
    command typed in an empty directory and the registrars create the workspace on the way in;
    opening it up front made a valid first declaration fail with `workspace.open.missing`, which
    sends the user to fix a directory when their file was correct.
    """
    unknown = sorted(set(document) - set(SECTIONS))
    if unknown:
        hint = ""
        if "sources" in unknown:
            hint = (
                ". Note: there is no top-level sources: section. A source is declared "
                "inline under its dataset (source_id + path), because a dataset and its "
                "file register as a pair"
            )
        found = collector(DECLARE_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.unknown_section",
                requirement=(
                    f"a declaration may contain: {', '.join(SECTIONS)}"
                ),
                observed=f"unknown: {', '.join(unknown)}{hint}",
                examples=unknown,
            )
        )
        found.done().raise_if_failed()
    opened: Workspace | None = None

    def workspace() -> Workspace:
        nonlocal opened
        if opened is None:
            opened = Workspace.open(project_root)
        return opened

    registered: dict[str, list[str]] = {}

    def section(key: str) -> dict[str, Any]:
        return _mapping(document.get(key) or {}, name=key)

    for dataset_id, body in section("datasets").items():
        registration, source = _dataset(str(dataset_id), body, base=base)
        register_dataset(project_root, registration, source)
        registered.setdefault("datasets", []).append(str(dataset_id))

    for input_id, body in section("execution_inputs").items():
        register_execution_input(project_root, _execution_input(str(input_id), body, base=base))
        registered.setdefault("execution_inputs", []).append(str(input_id))

    for agenda_id, body in section("agendas").items():
        register_agenda(project_root, _agenda(str(agenda_id), body, workspace()))
        registered.setdefault("agendas", []).append(str(agenda_id))

    for component_id, body in section("components").items():
        registered.setdefault("components", []).append(
            _component(str(component_id), body, project_root, base=base)
        )

    for component_id, body in section("strategy_configs").items():
        name = f"strategy_configs.{component_id}"
        config = _mapping(body, name=name)
        register_strategy_config(
            project_root,
            StrategyConfig(
                workspace().component(str(component_id)),
                str(_required(config, "agenda_id", name=name)),
                OperationRole.STRATEGY_CALLBACK,
            ),
        )
        registered.setdefault("strategy_configs", []).append(str(component_id))

    for config_id, body in section("valuation_configs").items():
        name = f"valuation_configs.{config_id}"
        config = _mapping(body, name=name)
        agenda_id = str(_required(config, "agenda_id", name=name))
        register_valuation_config(
            project_root, ValuationConfig(agenda_id, OperationRole.VALUATION)
        )
        registered.setdefault("valuation_configs", []).append(str(config_id))

    for policy_id, body in section("monitoring_policies").items():
        name = f"monitoring_policies.{policy_id}"
        policy = _mapping(body, name=name)
        agenda_id = str(_required(policy, "agenda_id", name=name))
        register_monitoring_policy(
            project_root, MonitoringPolicy(agenda_id, OperationRole.MONITORING)
        )
        registered.setdefault("monitoring_policies", []).append(str(policy_id))

    return registered


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "declaration",
        type=Path,
        help="path to the declaration YAML to validate and register",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    declaration = Path(args.declaration)
    document = read_yaml_mapping(declaration, what="a declaration")
    return success(
        "workspace.register",
        registered=apply(document, project_root, base=declaration.parent),
    )
