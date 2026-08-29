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
import ast
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from datetime import date, datetime, time
from difflib import get_close_matches
from enum import Enum
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import INCOMPLETE, VALUE_INVALID, InputError, read_yaml_mapping
from vqapr.domain import identifiers
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    collector,
)
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
    "instruments",
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


_declaration_path: ContextVar[Path | None] = ContextVar("_declaration_path", default=None)
"""The declaration file the current `apply` is reading, for `FailureSource.file`.

Every refusal in this module already knows its `key_path` -- the parser threads a `name` through
the eleven small helpers below. What it did not know was WHICH document that key lives in, and
that is the one thing a reader needs to open the right file. Threading a twelfth parameter through
all of them to carry a value that is constant for the whole call would be noise at every signature
for a fact that changes once.

A ContextVar rather than a module global because it is set and reset around one call, so a nested
or concurrent `apply` cannot see another's document.
"""


def _nearest_hint(written: str, permitted: Sequence[str], key_path: str) -> str:
    """What to write instead, naming the closest legal value when the written one is a near miss.

    A refusal that repeats the permitted set has told the reader nothing new -- `requirement`
    already listed it. What the reader cannot see is which of those values they were reaching for,
    and a one-character typo is invisible precisely to the person who typed it.
    """
    close = get_close_matches(written.lower(), [value.lower() for value in permitted], n=1)
    if close:
        return (
            f"set {key_path} to {close[0]!r}, which is the closest permitted value "
            f"to {written!r}"
        )
    return f"replace {written!r} at {key_path} with one of: {', '.join(permitted)}"


def _at(key_path: str) -> FailureSource:
    """Where a refusal points: the current declaration file, at this key.

    `line` stays absent on purpose. `yaml.safe_load` discards position information, so a line
    number here would have to be invented, and a wrong line is worse than none -- it sends the
    reader confidently to the wrong place.
    """
    declaration = _declaration_path.get()
    return FailureSource(
        file=None if declaration is None else str(declaration),
        key_path=key_path,
    )


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
                source=_at(name),
                fix=f"add {key} under {name} in the declaration YAML",
                explain=ExplainTopic.DECLARATION_SHAPE,
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


def _instruments(bodies: dict[str, Any], project_root: Path, *, base: Path) -> dict[str, Any]:
    """Register the project's instrument roster from its kind-keyed tables.

    **Validates what the file actually contains, not what the exporter promised.** A roster
    parquet may have been written by `instruments.py`, by hand, or by a script that got the schema
    wrong, and all three arrive here identically. Producing a clean file is the user's
    responsibility; refusing a dirty one is this function's -- the same split `available_at`
    already states.

    Returns a per-category receipt. That receipt is the one MECHANICAL guard against a mechanical
    sweep, and it works because it fires on the success path: an author who declared 2,143 names
    and is shown `{"stock": 2143}` has been told at registration that their universe is uniform,
    rather than discovering it in a later refusal. A uniform universe is a legitimate answer; this
    only makes it impossible to give without seeing it.
    """
    import hashlib

    from vqapr.domain.roster import build_roster
    from vqapr.domain.roster_export import read_roster_table
    from vqapr.workspace import Workspace

    name = "instruments"
    if "tables" not in bodies:
        # The old shape named the roster: `instruments: {<id>: {tables: ...}}`. The workspace has
        # one roster slot and stores no id, so that id was echoed back and discarded -- a
        # declaration syntax inviting something the product cannot hold. Refused outright rather
        # than accepted-and-ignored, because accepting it would be a compatibility shim for a
        # statement that was never true.
        named = ", ".join(sorted(str(key) for key in bodies)) or "nothing"
        raise InputError(
            VALUE_INVALID,
            requirement=(
                "`instruments:` declares one roster's tables directly, with no id above them"
            ),
            observed=f"`instruments:` maps to {named} rather than to `tables`",
            fix=(
                "remove the id line under `instruments:` and lift `tables:` up one level; a "
                "project holds one roster and each registration replaces it, so it has no name"
            ),
            explain=ExplainTopic.DECLARATION_SHAPE,
        )
    tables = _mapping(_required(bodies, "tables", name=name), name=f"{name}.tables")

    resolved: dict[str, Path] = {}
    rows: dict[str, dict[str, str]] = {}
    digest = hashlib.sha256()
    for kind, raw_path in sorted(tables.items()):
        path = (base / str(raw_path)).resolve()
        try:
            rows[str(kind)] = read_roster_table(path)
        except (FileNotFoundError, ValueError) as error:
            raise InputError(
                VALUE_INVALID,
                requirement=f"{name}.tables.{kind} must name a readable instrument table",
                observed=str(error),
                fix=f"write {path.name} with instrument_id and kind columns, then re-register",
                explain=ExplainTopic.DECLARATION_SHAPE,
                source=FailureSource(file=str(path)),
            ) from error
        resolved[str(kind)] = path
        # Digested over the file bytes, the same discipline `fingerprint_component` uses for a
        # user-authored component. Stated in the run record, never compared against it.
        digest.update(path.read_bytes())

    try:
        roster = build_roster(rows)
    except ValueError as error:
        # The declared tables, so a reader knows WHICH file to open. The exporter guarantees a
        # clean table; a hand-written or hand-edited one is a legitimate input and arrives here
        # identically, and that is the case this refusal is for -- an unsupported `kind` in a row
        # never comes from `instruments.py`, only from editing its output or writing the parquet
        # directly. `build_roster` names the instrument; this names the files it came from.
        declared_files = ", ".join(
            f"{kind}={path.name}" for kind, path in sorted(resolved.items())
        )
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must describe every instrument exactly once, under its own kind",
            observed=f"{error} (declared tables: {declared_files})",
            fix=(
                "correct the instrument tables so each id appears once under a declared kind; "
                "re-running the emitted instruments.py produces a table that satisfies this"
            ),
            explain=ExplainTopic.DECLARATION_SHAPE,
        ) from error

    workspace = Workspace.open(project_root)
    workspace.register_instruments(resolved, digest=digest.hexdigest())
    # No `roster_id`: the workspace stores `schema`, `tables` and `digest` and no id, so echoing
    # one back would report an identity nothing kept. The digest is the roster's actual handle,
    # and it is what `run` states.
    receipt: dict[str, object] = {
        "instruments": len(roster),
        "by_kind": roster.histogram,
        "digest": digest.hexdigest(),
    }
    undeclared = _undeclared_roster_tables(resolved)
    if undeclared:
        receipt["undeclared"] = undeclared
    return receipt


def _undeclared_roster_tables(resolved: Mapping[str, Path]) -> list[str]:
    """Roster tables sitting beside the declared ones that the declaration did not name.

    The emitted `instruments.yaml` ships `stock:` live and `etf:`, `index:` and `factor:`
    commented. An author who exports twelve names across two categories and registers the template
    unchanged registers **ten**, and the ETF table sits beside it undeclared. The per-category
    receipt made that legible -- `{"stock": 10}` against a universe of twelve -- but only to a
    reader who noticed a number.

    Reported, not refused. Declaring a subset is legitimate: a project may export every category
    its exporter knows and trade only equities. What is not legitimate is doing it by accident, so
    this names the file rather than deciding for the author.

    Matched by the exporter's own `<stem>_<kind>.parquet` convention, derived from the declared
    files rather than assumed, so a hand-written roster under any other naming reports nothing
    instead of reporting noise.

    The candidates are the four known categories by name, not a `{prefix}_*.parquet` glob. A glob
    accepts any suffix, so a project with `universe_stock.parquet` beside an unrelated
    `universe_prices.parquet` would have the second reported as an undeclared roster table -- a
    false line in a success receipt, which is the one thing a receipt read on the success path
    must not carry.
    """
    from vqapr.domain.instruments import InstrumentKind

    declared = {path.resolve() for path in resolved.values()}
    prefixes: set[tuple[Path, str]] = set()
    for kind, path in resolved.items():
        stem = path.stem
        suffix = f"_{kind}"
        if stem.endswith(suffix):
            prefixes.add((path.parent, stem[: -len(suffix)]))
    found: set[str] = set()
    for parent, prefix in prefixes:
        for known in InstrumentKind:
            candidate = parent / f"{prefix}_{known}.parquet"
            if candidate.is_file() and candidate.resolve() not in declared:
                found.add(candidate.name)
    return sorted(found)


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
            _enum(
                FillSelector,
                _required(fill, "selector", name=f"{name}.fill"),
                name=f"{name}.fill.selector",
            ),
            _time(_required(fill, "at", name=f"{name}.fill"), name=f"{name}.fill.at"),
            str(_required(fill, "timezone", name=f"{name}.fill")),
            str(_required(fill, "trade_price", name=f"{name}.fill")),
        ),
    )


def _sessions(
    body: dict[str, Any], workspace: Callable[[], Workspace], *, name: str
) -> list[datetime | date]:
    """Where an agenda's days come from: a dataset it follows, or an explicit list.

    `from_dataset` is the common case and the one worth making short. A cadence usually follows
    the data it reads, and `Workspace.evaluation_times` already knows those days exactly, so
    restating them by hand is a chance to disagree with the dataset for no benefit.

    `_require_agenda_keys` has already proven exactly one of the two is present, so the guard here
    is the same kind of fallback `_required` is: reached only through a path that skipped the
    pre-check, and typed rather than bare so it cannot land in the envelope as `stage:"unhandled"`.
    """
    dataset_id = body.get("from_dataset")
    declared = body.get("sessions")
    if (dataset_id is None) == (declared is None):
        _refuse_agenda_source(body, name=name)
    if dataset_id is not None:
        return list(workspace().evaluation_times(str(dataset_id)))
    if not isinstance(declared, list) or not declared:
        found = collector(DECLARE_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.value_invalid",
                requirement=f"{name}.sessions must be a non-empty list of dates",
                observed=f"{type(declared).__name__}: {declared!r}"[:200],
                examples=["sessions: ['2024-01-02', '2024-01-03']"],
                source=_at(f"{name}.sessions"),
                fix=(
                    f"set {name}.sessions to a non-empty list of ISO dates, "
                    "or use from_dataset instead"
                ),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
        found.done().raise_if_failed()
    return [
        value if isinstance(value, (datetime, date)) else date.fromisoformat(str(value))
        for value in declared
    ]


def _enum[E: Enum](kind: type[E], value: object, *, name: str) -> E:
    """Read a declared enum value, or refuse by naming every member.

    A bare `Kind[value.upper()]` raises `KeyError`, which reaches the envelope as
    `stage:"unhandled"` with an empty `failures[]` and a traceback file. A reader who cannot see
    the member list then guesses, and guessing converges only when the field name happens to
    suggest the right vocabulary.

    Measured: `fill.selector` was a raw lookup, and a reader spent six consecutive attempts on
    `close, market, close_price, last, vwap, next_open` — every one a *price* word, because
    "selector" alongside `trade_price` reads as "which price". The members are `SAME_DAY` and
    `NEXT_ELIGIBLE`, which are *scheduling* words. No number of guesses reaches a vocabulary the
    field name argues against, so the refusal has to carry the list.
    """
    try:
        return kind[str(value).upper()]
    except KeyError:
        permitted = ", ".join(member.name.lower() for member in kind)
        found = collector(DECLARE_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.value_not_permitted",
                requirement=f"{name} must be one of: {permitted}",
                observed=str(value),
                examples=[member.name.lower() for member in kind],
                source=_at(name),
                # Names the value actually written and the nearest legal one. Repeating the
                # permitted set with the verb swapped would say nothing `requirement` has not
                # already said, and a near-miss is usually a typo the reader cannot see.
                fix=_nearest_hint(str(value), [member.name.lower() for member in kind], name),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
        found.done().raise_if_failed()
        raise  # unreachable: raise_if_failed always raises here


def _role(value: object, *, name: str) -> OperationRole:
    return _enum(OperationRole, value, name=f"{name}.role")


_AGENDA_KEYS = ("role", "at", "timezone")
"""Every key an agenda declaration must carry outright.

Its session source is not here because it is a choice of two keys rather than one required key;
`_require_agenda_keys` checks both together so a reader still sees one refusal.
"""


def _refuse_agenda_source(body: dict[str, Any], *, name: str) -> None:
    """Refuse an agenda that names neither session source, or both."""
    declares_both = "from_dataset" in body and "sessions" in body
    found = collector(DECLARE_STAGE, FailureFamily.DATA)
    found.add(
        Failure.bounded(
            f"{DECLARE_STAGE}.key_missing",
            requirement=(
                f"{name} must declare exactly one of from_dataset or sessions: "
                "from_dataset follows a registered dataset's own days, "
                "sessions lists them literally"
            ),
            observed=(
                f"{name} declares both"
                if declares_both
                else f"{name} declares: {', '.join(sorted(body)) or '(nothing)'}"
            ),
            examples=["from_dataset: krx_adjusted_prices", "sessions: ['2024-01-02']"],
            source=_at(name),
            fix=(
                f"remove one of from_dataset/sessions from {name}"
                if declares_both
                else f"add either from_dataset or sessions under {name}"
            ),
            explain=ExplainTopic.DECLARATION_SHAPE,
        )
    )
    found.done().raise_if_failed()


def _require_agenda_keys(body: dict[str, Any], *, name: str) -> None:
    """Name everything one agenda declaration is missing, in a single refusal.

    `_require_keys` alone is not enough here: an agenda's session source is `from_dataset` **or**
    `sessions`, which no required-key list can express, so checking the two separately produces a
    reader who fixes `role`, re-runs, and only then learns about the pair.

    Measured, before this: a first-time reader assembling one agenda by hand took **four**
    register/edit/retry round trips, one per key, each refusal naming exactly one problem
    (`role`, then a wrong role value, then the from_dataset/sessions pair, then `timezone`).
    `_DATASET_KEYS` had already fixed this shape for datasets; agendas were simply missed.
    """
    missing = [key for key in _AGENDA_KEYS if key not in body]
    has_source = ("from_dataset" in body) != ("sessions" in body)
    if not missing:
        if not has_source:
            _refuse_agenda_source(body, name=name)
        return

    found = collector(DECLARE_STAGE, FailureFamily.DATA)
    declares = f"{name} declares: {', '.join(sorted(body)) or '(nothing)'}"
    for key in missing:
        requirement = f"{name} must declare {key}"
        if key == "role":
            permitted = ", ".join(member.name.lower() for member in OperationRole)
            requirement = f"{requirement}, one of: {permitted}"
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.key_missing",
                requirement=requirement,
                observed=declares,
                source=_at(f"{name}.{key}"),
                fix=f"add {key} under {name} in the declaration YAML",
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
    if not has_source:
        declares_both = "from_dataset" in body and "sessions" in body
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.key_missing",
                requirement=(
                    f"{name} must declare exactly one of from_dataset or sessions"
                ),
                observed=f"{name} declares both" if declares_both else declares,
                source=_at(name),
                fix=(
                    f"remove one of from_dataset/sessions from {name}"
                    if declares_both
                    else f"add either from_dataset or sessions under {name}"
                ),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
    found.done().raise_if_failed()


def _agenda(
    agenda_id: str, declared: object, workspace: Callable[[], Workspace]
) -> OperationAgenda:
    """Build one agenda through `daily()`, which owns the rules a hand-built one gets wrong.

    `OperationAgenda.daily` derives the occurrence id scheme, the fold, and the offset from the
    zone. A file that typed those constants itself would be correct until the venue observed DST.
    """
    name = f"agendas.{agenda_id}"
    body = _mapping(declared, name=name)
    _require_agenda_keys(body, name=name)
    return OperationAgenda.daily(
        agenda_id=agenda_id,
        role=_role(_required(body, "role", name=name), name=name),
        sessions=_sessions(body, workspace, name=name),
        at=_time(_required(body, "at", name=name), name=f"{name}.at"),
        timezone=str(_required(body, "timezone", name=name)),
        provenance=str(body.get("provenance", f"vqapr register: {agenda_id}")),
    )


_DECLARED_IDS = {
    "datasets": ("dataset id", identifiers.dataset_id),
    "execution_inputs": ("execution input id", identifiers.execution_input_id),
    "agendas": ("agenda id", identifiers.agenda_id),
    "components": ("component id", identifiers.component_id),
    "strategy_configs": ("component id", identifiers.component_id),
}
"""Sections whose KEY becomes a typed identifier, and the constructor that judges it.

Every one of these refuses an empty string, one with surrounding whitespace, or one containing any
-- with a bare `ValueError`. For four of the five nothing caught it, so a blank or padded key in a
declaration reached the envelope as `stage:"unhandled"` with an empty `failures[]`: the framework
reporting itself broken over a fat-fingered YAML key. `strategy_configs` is the exception --
`Workspace.component()` already converted that `ValueError` into a structured refusal -- and it is
here so the rule stays one rule: the key of every section listed becomes a typed identifier, and
every one of them is judged in the same place, at the same time, with the same refusal naming the
section it came from.

One table rather than a check inside each section handler, because the first fix here covered only
`components` and red-teaming immediately found `datasets` and `execution_inputs` still crashing.
A per-handler check is a list you can be one short of; this is the list.
"""


def _require_declared_ids(section: Any) -> None:
    """Refuse every unusable declaration key at once, before anything is registered.

    Up front rather than per section: registration mutates the workspace, and validating as each
    loop reaches it would let a bad key in `components` land after `datasets` had already been
    written. Collected rather than stopping at the first, for the reason the whole surface
    collects -- a document with three bad keys should cost one command, not three.
    """
    found = collector(DECLARE_STAGE, FailureFamily.DATA)
    for key, (label, judge) in _DECLARED_IDS.items():
        for declared in section(key):
            raw = str(declared)
            try:
                judge(raw)
            except (TypeError, ValueError) as invalid:
                found.add(
                    Failure.bounded(
                        f"{DECLARE_STAGE}.value_invalid",
                        requirement=(
                            f"a {label} must be a non-empty string with no whitespace inside it "
                            "and none around it"
                        ),
                        observed=f"{raw!r}: {invalid}",
                        source=_at(key),
                        fix=(
                            f"rename the key under `{key}:` to a non-empty identifier without "
                            "spaces, such as `daily-prices`"
                        ),
                        explain=ExplainTopic.DECLARATION_SHAPE,
                    )
                )
    found.done().raise_if_failed()


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
        # Named like `_enum` does, for the same reason: a bare raise reaches the envelope as
        # `stage:"unhandled"` with an empty `failures[]`, and a reader who cannot see the member
        # list guesses at it.
        permitted = ", ".join(_COMPONENT_KINDS)
        found = collector(DECLARE_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.value_not_permitted",
                requirement=f"{name}.kind must be one of: {permitted}",
                observed=raw_kind,
                examples=list(_COMPONENT_KINDS),
                source=_at(f"{name}.kind"),
                fix=_nearest_hint(str(raw_kind), list(_COMPONENT_KINDS), f"{name}.kind"),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
        found.done().raise_if_failed()
    _, register = _COMPONENT_KINDS[raw_kind]
    config = body.get("config")
    if config is not None and not isinstance(config, dict):
        found = collector(DECLARE_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                f"{DECLARE_STAGE}.value_invalid",
                requirement=f"{name}.config must be a mapping of constructor keywords",
                observed=f"{type(config).__name__}: {config!r}"[:200],
                source=_at(f"{name}.config"),
                fix=f"rewrite {name}.config as a mapping of constructor keyword arguments",
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
        found.done().raise_if_failed()
    declared_path = Path(str(_required(body, "path", name=name)))
    ref = register(
        project_root,
        component_id,
        declared_path if declared_path.is_absolute() else base / declared_path,
        str(_required(body, "object_name", name=name)),
        config=config,
    )
    return str(ref.component_id)


def apply(
    document: dict[str, Any],
    project_root: Path,
    *,
    base: Path,
    declaration: Path | None = None,
) -> dict[str, list[str]]:
    """Apply every section the document declares, in dependency order.

    Returns what was registered per section, so the reply states facts rather than a count.

    The workspace is opened **only when a section needs to read one**. `register` is the first
    command typed in an empty directory and the registrars create the workspace on the way in;
    opening it up front made a valid first declaration fail with `workspace.open.missing`, which
    sends the user to fix a directory when their file was correct.

    `declaration` is the document's own path, and it is what every refusal below reports as
    `source.file`. It is optional because a caller may hold a parsed document with no file behind
    it; when it is absent the refusals say so rather than naming a path that does not exist.
    """
    token = _declaration_path.set(declaration)
    try:
        return _apply(document, project_root, base=base)
    finally:
        _declaration_path.reset(token)


def _apply(document: dict[str, Any], project_root: Path, *, base: Path) -> dict[str, list[str]]:
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
                fix=f"remove or rename the unrecognized section(s): {', '.join(unknown)}",
                explain=ExplainTopic.DECLARATION_SHAPE,
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

    _require_declared_ids(section)

    instrument_bodies = section("instruments")
    if instrument_bodies:
        receipt = _instruments(instrument_bodies, project_root, base=base)
        registered.setdefault("instruments", []).append(receipt)

    for dataset_id, body in section("datasets").items():
        registration, source = _dataset(str(dataset_id), body, base=base)
        register_dataset(project_root, registration, source)
        registered.setdefault("datasets", []).append(str(dataset_id))

    for input_id, body in section("execution_inputs").items():
        register_execution_input(project_root, _execution_input(str(input_id), body, base=base))
        registered.setdefault("execution_inputs", []).append(str(input_id))

    for agenda_id, body in section("agendas").items():
        # `workspace` is passed unopened. Evaluating `workspace()` here instead would open it
        # before the agenda body is validated, so a malformed agenda in a fresh directory reports
        # `workspace.open.missing` -- sending the reader to fix a directory when the file on
        # their disk is what needs editing, which is the exact substitution the lazy accessor
        # exists to prevent.
        register_agenda(project_root, _agenda(str(agenda_id), body, workspace))
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


def _register_authored(
    kind: str, component_id: str | None, source: Path | None, project_root: Path
) -> dict[str, Any]:
    """Register one Python-authored component by naming its kind, id and file.

    The declaration form still exists and still owns datasets, sources, agendas and configs. What
    this removes is the YAML wrapper around a COMPONENT, whose entire content was the three facts
    already on this command line -- and which stood between an author writing a strategy in Python
    and registering it.
    """
    if component_id is None or source is None:
        raise InputError(
            INCOMPLETE,
            requirement=f"register {kind} needs a component id and a path to its .py",
            observed=f"register {kind}"
            + (f" {component_id}" if component_id else " <id> <file.py>"),
            retry=f"run `vqapr register {kind} <component-id> <file.py>`",
        )

    path = Path(source)
    if not path.is_file():
        raise InputError(
            VALUE_INVALID,
            requirement="the component source must be a file that exists",
            observed=f"no file at {path.resolve()}",
            retry=f"write one with `vqapr new {kind} {component_id}`, then register it",
            source=FailureSource(file=str(path)),
        )

    expected = AUTHORED_KINDS[kind]
    # Found by parsing before the register call, so "two strategies in one file" is refused as
    # that, rather than surfacing as whatever the loader happens to say about an ambiguous import.
    object_name = _sole_subclass(path, expected, component_id)
    _COMPONENT_KINDS[kind][1](project_root, component_id, path, object_name)
    return success(
        "workspace.register",
        registered={"components": [component_id]},
        component={"id": component_id, "kind": kind, "object": object_name, "source": str(path)},
    )


def _sole_subclass(path: Path, kind: ComponentKind, component_id: str) -> str:
    """The one authored class in this file, refusing zero and refusing several.

    AC-A4. Both refusals state the COUNT, because "which class did you mean" and "you wrote none"
    are different mistakes with different repairs, and a reader who is told only that the file is
    invalid has to guess which one they made. Found by parsing rather than importing: a file with
    two strategies should be refused for having two, not for whatever its import happens to do.
    """
    base = {
        ComponentKind.STRATEGY_MODEL: "StrategyModel",
        ComponentKind.DATA_MODEL: "DataModel",
        ComponentKind.CONSTRAINT: "Constraint",
    }[kind]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as broken:
        raise InputError(
            VALUE_INVALID,
            requirement="the component source must be readable Python",
            observed=f"{path}: {broken}",
            retry="fix the syntax error, then register again",
            source=FailureSource(file=str(path)),
        ) from broken

    # Local names that refer to the authoring base, including aliases. `import StrategyModel as
    # SM` used to produce a false "defines 0" about a file that defines exactly one -- and since
    # the COUNT is the evidence AC-A4 rests on, a wrong count is the specific thing that criterion
    # forbids.
    aliases = {base}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name == base:
                    aliases.add(imported.asname or imported.name)

    # Walk the whole tree, not just the module body: a class defined inside an `if` or a `try` is
    # still a class the file defines, and reporting zero for it sends the author to write one they
    # already wrote.
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

    def _names(node: ast.ClassDef) -> set[str]:
        return {
            b.id if isinstance(b, ast.Name) else b.attr
            for b in node.bases
            if isinstance(b, (ast.Name, ast.Attribute))
        }

    # Follow the inheritance chain. `class Base(StrategyModel)` plus `class Mine(Base)` used to
    # match only Base, which counts as one and registers the WRONG class -- the run then executes
    # Base while the author believes Mine ran. Both are subclasses; the LEAF is the one meant.
    subclasses: dict[str, ast.ClassDef] = {}
    pending = True
    while pending:
        pending = False
        for node in classes:
            if node.name not in subclasses and _names(node) & (aliases | set(subclasses)):
                subclasses[node.name] = node
                pending = True

    # A class that something else in this file inherits from is scaffolding for the leaf, not the
    # component itself.
    inherited = {name for node in classes for name in _names(node)}
    found = [name for name in subclasses if name not in inherited]
    if len(found) == 1:
        return found[0]
    if not found:
        raise InputError(
            VALUE_INVALID,
            requirement=f"the file must define exactly one {base} subclass",
            observed=f"{path} defines 0",
            retry=f"add a `class {component_id.title().replace('-', '')}({base}):` to {path.name}",
            source=FailureSource(file=str(path)),
        )
    raise InputError(
        VALUE_INVALID,
        requirement=f"the file must define exactly one {base} subclass",
        observed=f"{path} defines {len(found)}: {', '.join(found)}",
        retry=(
            f"keep one {base} in {path.name} and move the others to their own files, "
            "each registered under its own component id"
        ),
        examples=found,
        source=FailureSource(file=str(path)),
    )


AUTHORED_KINDS = {
    "strategy": ComponentKind.STRATEGY_MODEL,
    "datamodel": ComponentKind.DATA_MODEL,
    "constraint": ComponentKind.CONSTRAINT,
}


def cli_kind(kind: object) -> str:
    """A component kind spelled the way this surface accepts it.

    `new` and `register` take `datamodel`; `show` and `list` reported `data_model`, which is the
    domain enum's value and a string a reader cannot type anywhere. A first-time-user journey hit
    that: one spelling on the way in, another on the way out.

    Derived from `AUTHORED_KINDS` rather than restated, so the two cannot disagree. A kind with no
    CLI spelling -- `exchange`, which is registered through a declaration rather than by naming a
    kind -- falls back to the enum's own value, which is what it is called everywhere else.
    """
    for spelling, authored in AUTHORED_KINDS.items():
        if authored is kind:
            return spelling
    return str(getattr(kind, "value", kind))
"""The component kinds an author writes as a `.py` and registers directly.

Everything else -- datasets, sources, agendas, configs -- stays in the YAML declaration, because
those ARE declarations: there is no code to point at. A component is different. Its identity is
its source file, and requiring a YAML wrapper to say so made the author write the same fact twice
and kept a Python-authored strategy from being registered by naming it.
"""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "declaration",
        type=Path,
        help=(
            "path to the declaration YAML, or the component kind "
            f"({', '.join(sorted(AUTHORED_KINDS))}) when registering a .py directly"
        ),
    )
    parser.add_argument(
        "component_id",
        nargs="?",
        default=None,
        help="component id, when the first argument is a component kind",
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="path to the .py, when the first argument is a component kind",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    kind = str(args.declaration)
    if kind in AUTHORED_KINDS:
        return _register_authored(
            kind, getattr(args, "component_id", None), getattr(args, "source", None), project_root
        )
    declaration = Path(args.declaration)
    document = read_yaml_mapping(declaration, what="a declaration")
    return success(
        "workspace.register",
        registered=apply(
            document, project_root, base=declaration.parent, declaration=declaration
        ),
    )
