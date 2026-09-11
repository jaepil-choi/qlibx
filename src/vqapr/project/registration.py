"""Turn a user-authored declaration document into registered workspace declarations.

**Moved out of `cli/register.py` by record `112`.** That module was 1,093 lines and held all of it:
reading a YAML mapping, validating its keys, resolving relative paths, parsing agendas and sessions,
walking a `.py` with `ast` to find the sole subclass, and registering the result. The CLI was not a
surface over this logic; it *was* this logic.

`docs/vqapr-architecture.md` §10.2 defines the CLI as a product surface rather than a layer, and a
surface that owns rules costs twice. The rules cannot be tested without driving argparse, and they
cannot be reached from another entry point -- so a second entry point grows its own copy and the two
diverge. `docs/issues/archive/012` is exactly that: `check` refused a spec `run` completed, because
each verb decided for itself.

`cli/register.py` keeps argparse wiring, one call into this module, and envelope rendering.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from difflib import get_close_matches
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from vqapr.data.datasets import GRAIN_NAMES, ROWS_LOOKBACK_MEANING, DatasetRegistration
from vqapr.data.scan import DECLARABLE_FIELD_TYPE_NAMES
from vqapr.data.sources import SourceSpec
from vqapr.data.validation import verify_roster, verify_source
from vqapr.domain import identifiers
from vqapr.domain.account import AccountMode
from vqapr.domain.errors import (
    INCOMPLETE,
    VALUE_INVALID,
    Diagnosis,
    Failure,
    FailureSource,
    InputError,
    Stage,
    Status,
    collector,
)
from vqapr.domain.instrument import export_roster
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.loading import authored_classes
from vqapr.extension.prepare import prepare_component
from vqapr.project.document import (
    ComponentDeclaration,
    DatasetDeclaration,
    InstrumentsDeclaration,
)
from vqapr.project.run import RunDefinition
from vqapr.project.store import Transaction, Workspace

_COMPONENT_KINDS = {
    "datamodel": ComponentKind.DATA_MODEL,
    "strategy": ComponentKind.STRATEGY_MODEL,
    "compliance": ComponentKind.COMPLIANCE,
    "exchange": ComponentKind.EXCHANGE,
}
"""확장점 넷 전부. canon §10.2가 닫아두지 말라고 한 목록이다.

무엇이 실제로 좁은 문인지는 `load_exchange`가 정한다 — shipped profile을 상속하지 않거나
`execute()`를 갈아치운 것은 거기서 거부된다. CLI가 kind 목록으로 막을 일이 아니다.
"""

SECTIONS = (
    "instruments",
    "datasets",
    "components",
    "runs",
)
"""Every section this command understands, in dependency order.

The order is a dependency order, not a preference: an agenda may read a dataset's sessions, and a
strategy config names both a component and an agenda that must already exist. Applying them in
file order would make a valid document fail because of the order the user typed it in.
"""

_SECTION_NOTES: dict[str, tuple[str, str]] = {
    "sources": (
        ". Note: there is no top-level sources: section. A source is declared "
        "inline under its dataset (source_id + path), because a dataset and its "
        "file register as a pair",
        "move each source under its dataset as source_id + path, then delete the sources: section",
    ),
}
"""A note and a fix for a section an author reasonably expects to exist, but that does not.

Only for names `_nearest_hint` cannot reach. A typo (`dataset`, `run`) is a near miss and the
nearest permitted name answers it; `sources` is not a misspelling of anything -- it is a section
the author was right to look for and that this package deliberately does not have, so the answer
has to be written out. Everything reachable by spelling stays out of this table.
"""


# Moved here from `vqapr.public` by record `112`, and re-exported there. Unlike the other
# `register_*` helpers these are not one-line delegations -- each validates before it writes --
# so this module cannot inline them without duplicating a rule. Importing them from the facade
# would be the fan-in this campaign removes, so the dependency is inverted instead: the layer
# owns them and the surface names them.
def register_dataset(
    project_root: str | Path,
    registration: DatasetRegistration,
    source: SourceSpec,
) -> bool:
    """준비된 parquet을 검증하고 project workspace에 등록한다.

    새 등록이면 ``True``, 디스크에 이미 같은 선언이 있으면 ``False``다. 검증이나 persistence가
    실패하면 ``VqaprError``를 발생시키며, 검증 실패는 workspace를 만들거나 바꾸지 않는다.
    """
    diagnosis, _, measured = verify_source(registration, source)
    diagnosis.raise_if_failed()
    # `measured` is the registration with its span filled in from the scan validation just ran.
    # Registering the caller's copy instead would persist a declaration missing the one fact only
    # a full read can establish, and the next reader would have to read the file again to get it.
    with Workspace.transaction(project_root) as transaction:
        return transaction.register_dataset(measured, source)


def register_instruments(
    project_root: str | Path,
    universe: Mapping[str, str],
    *,
    directory: str | Path | None = None,
) -> dict[str, Any]:
    """Declare what each instrument IS and register the roster, in one call (design §6.2).

    `universe` is the flat `{instrument_id: kind}` an author naturally builds. The per-kind
    tables are exported under `directory` (default `<project_root>/instruments`) and registered
    through the same door `vqapr register instruments.yaml` uses, so an in-process caller and a
    CLI user land on one roster slot with one receipt. Returns that receipt: `instruments`,
    `by_kind`, `digest`.

    Re-registering is ordinary -- a roster grows -- and replaces the whole slot.
    """
    root = Path(project_root)
    target = Path(directory) if directory is not None else root / "instruments"
    written = export_roster(universe, target)
    document = {
        "instruments": {"tables": {kind: path.name for kind, path in sorted(written.items())}}
    }
    registered = apply(document, root, base=target)
    (receipt,) = registered["instruments"]
    if not isinstance(receipt, dict):
        raise RuntimeError("apply registered a roster without its receipt")
    return receipt


def _mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping")
    return value


def _nearest_hint(
    written: str, permitted: Sequence[str], key_path: str, *, removable: bool = False
) -> str:
    """What to write instead, naming the closest legal value when the written one is a near miss.

    A refusal that repeats the permitted set has told the reader nothing new -- `requirement`
    already listed it. What the reader cannot see is which of those values they were reaching for,
    and a one-character typo is invisible precisely to the person who typed it.

    `removable` says whether deleting what was written is one of the answers. It is for a key the
    author invented -- an unknown section, an unknown field -- and it is not for a value in a
    closed set, where the field is required and deleting the value leaves the declaration
    incomplete. Only the caller knows which of the two it holds, so only the caller can say.
    """
    close = get_close_matches(written.lower(), [value.lower() for value in permitted], n=1)
    if close:
        return (
            f"set {key_path} to {close[0]!r}, which is the closest permitted value to {written!r}"
        )
    if removable:
        # A top-level section IS its own key path, and "remove 'agendas' at agendas" says the
        # name twice. Deeper, `runs.r.foo` is where a bare `foo` would leave the reader looking.
        where = "" if key_path == written else f" at {key_path}"
        return f"remove {written!r}{where}, or replace it with one of: {', '.join(permitted)}"
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


def refusals_from(
    error: ValidationError,
    *,
    model: type[BaseModel],
    name: str,
    also: Sequence[Failure] = (),
) -> Diagnosis:
    """Every finding pydantic made about one declaration, as this package's refusals.

    pydantic owns the key sets, the types, the enums and the timestamps of a declaration
    (record `145`); what it must not own is the sentence an author reads. Each line error
    becomes one `Failure` with the package's own `code`, status 400 (the document is what must
    change), a `fix` that says what to write and a `source` at the dotted key path -- and all of
    them travel in ONE `Diagnosis`, which is what `_require_keys` promised: an agent fixing its
    declaration is told every problem at once, not one per round trip. The `ValidationError`
    itself rides on every entry as `cause`.

    Four shapes, four codes. A missing key (`key_missing`) names what the declaration does
    have, so the reader sees the set whole. An unknown key (`key_unknown`) and a value outside a
    closed set (`value_not_permitted`) get `_nearest_hint`: the reader cannot see the one-letter
    typo they typed. Everything else is `value_invalid` at its own path. Nothing pydantic wrote
    reaches the envelope; its `msg` is a hint for the requirement sentence and no more.
    """
    found = collector(Stage.REGISTER)
    for extra in also:
        found.add(extra)
    for line in error.errors(include_url=False):
        loc = tuple(str(part) for part in line["loc"])
        kind = line["type"]
        if kind == "missing":
            parent, key = ".".join((name, *loc[:-1])), loc[-1]
            # For a missing key pydantic's `input` is the mapping that lacks it.
            present = _keys_present(line["input"])
            vocabulary = _permitted_values(model, loc)
            found.add(
                Failure.bounded(
                    "declaration.key_missing",
                    status=Status.INVALID,
                    cause=error,
                    requirement=(
                        f"{parent} must declare {key}"
                        + (f", one of: {', '.join(vocabulary)}" if vocabulary else "")
                    ),
                    observed=f"{parent} declares: {', '.join(present) or '(nothing)'}",
                    source=_at(parent),
                    fix=f"add {key} under {parent} in the declaration YAML",
                )
            )
        elif kind == "extra_forbidden":
            parent, key = ".".join((name, *loc[:-1])), loc[-1]
            permitted = _permitted_keys(model, loc[:-1])
            found.add(
                Failure.bounded(
                    "declaration.key_unknown",
                    status=Status.INVALID,
                    cause=error,
                    requirement=f"{parent} may declare: {', '.join(permitted)}",
                    observed=f"{parent} declares {key!r}, which is not one of them",
                    examples=[key],
                    source=_at(f"{parent}.{key}"),
                    fix=(
                        _nearest_hint(key, permitted, f"{parent}.{key}", removable=True).replace(
                            "set ", "rename ", 1
                        )
                        if permitted
                        else f"remove {key} from {parent}"
                    ),
                )
            )
        elif kind in ("enum", "literal_error"):
            path = ".".join((name, *loc))
            expected = _expected_members(line)
            written = str(line.get("input"))
            found.add(
                Failure.bounded(
                    "declaration.value_not_permitted",
                    status=Status.INVALID,
                    cause=error,
                    requirement=f"{path} must be one of: {', '.join(expected)}",
                    observed=written,
                    examples=expected,
                    source=_at(path),
                    fix=_nearest_hint(written, expected, path),
                )
            )
        else:
            path = ".".join((name, *loc))
            found.add(
                Failure.bounded(
                    "declaration.value_invalid",
                    status=Status.INVALID,
                    cause=error,
                    requirement=f"{path} must be {_shape_words(line)}",
                    observed=f"{path} is {line.get('input')!r}",
                    source=_at(path),
                    fix=f"correct {path} in the declaration YAML",
                )
            )
    return found.done()


def _keys_present(body: object) -> list[str]:
    return sorted(str(key) for key in body) if isinstance(body, dict) else []


def _permitted_values(model: type[BaseModel], loc: tuple[str, ...]) -> list[str]:
    """The closed set a field at `loc` takes (a `Literal` or an enum), else nothing.

    Said in the refusal for a MISSING key, because a reader's next guess at `role` is otherwise
    "strategy" -- `tests/cli/test_register.py` measured it.
    """
    import enum
    import typing

    fields = getattr(model, "model_fields", None)
    if not loc or fields is None or loc[-1] not in fields:
        return []
    annotation = fields[loc[-1]].annotation
    if typing.get_origin(annotation) is typing.Literal:
        return [str(member) for member in typing.get_args(annotation)]
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return [str(member.value) for member in annotation]
    return []


def declared[M: BaseModel](model: type[M], body: object, *, name: str, also=()) -> M:
    """One declaration through its model, or every fault in one refusal."""
    try:
        return model.model_validate(body)
    except ValidationError as invalid:
        refusals_from(invalid, model=model, name=name, also=tuple(also)).raise_if_failed()
        raise AssertionError("unreachable") from invalid


def _permitted_keys(model: type[BaseModel], loc: tuple[str, ...]) -> list[str]:
    """The field names of the model at `loc`, or none when the path does not reach a model."""
    current: object = model
    for part in loc:
        fields = getattr(current, "model_fields", None)
        if fields is not None and part in fields:
            current = _model_of(fields[part].annotation)
        else:
            # A mapping value (`dict[str, Model]`): the key is the author's, the value's model
            # is the annotation's argument.
            current = _mapping_value_model(current)
        if current is None:
            return []
    fields = getattr(current, "model_fields", None)
    return sorted(fields) if fields else []


def _model_of(annotation: object) -> object:
    """The BaseModel a field annotation names, through `Optional`/`Union` and `dict[str, M]`."""
    import types
    import typing

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        for argument in typing.get_args(annotation):
            model = _model_of(argument)
            if model is not None:
                return model
        return None
    if origin in (dict, typing.Mapping):
        return _Mapping(_model_of(typing.get_args(annotation)[1]))
    return None


class _Mapping:
    """A `dict[str, M]` on the way down `_permitted_keys`: any key, then M's fields."""

    def __init__(self, value_model: object) -> None:
        self.value_model = value_model


def _mapping_value_model(current: object) -> object:
    return current.value_model if isinstance(current, _Mapping) else None


def _expected_members(line: Mapping[str, Any]) -> list[str]:
    context = line.get("ctx") or {}
    expected = str(context.get("expected", ""))
    members = [part.strip().strip("'\"") for part in expected.replace(" or ", ", ").split(",")]
    return [member for member in members if member]


def _shape_words(line: Mapping[str, Any]) -> str:
    """A requirement clause from pydantic's error type, never its sentence."""
    kind = str(line["type"])
    words = {
        "string_type": "a string",
        "int_type": "an integer",
        "int_parsing": "an integer",
        "bool_type": "true or false",
        "bool_parsing": "true or false",
        "float_type": "a number",
        "decimal_type": "a decimal, quoted to keep its digits",
        "decimal_parsing": "a decimal, quoted to keep its digits",
        "dict_type": "a mapping",
        "list_type": "a list",
        "tuple_type": "a list",
        "model_type": "a mapping",
        "datetime_type": "an ISO-8601 datetime with an offset",
        "datetime_parsing": "an ISO-8601 datetime with an offset",
        "datetime_from_date_parsing": "an ISO-8601 datetime with an offset",
        "date_type": "an ISO-8601 date",
        "date_from_datetime_parsing": "an ISO-8601 date",
        "time_type": "a local time such as '15:30'",
        "time_parsing": "a local time such as '15:30'",
        "timezone_aware": "a datetime with an offset",
        "value_error": str(line.get("ctx", {}).get("error", "")).removeprefix("Value error, ")
        or "a valid value",
    }
    return words.get(kind, "a valid value")


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


def _instruments(bodies: dict[str, Any], transaction: Transaction, *, base: Path) -> dict[str, Any]:
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

    from vqapr.domain.instrument import build_roster

    name = "instruments"
    retired = bool(bodies) and all(
        isinstance(body, dict) and "tables" in body for body in bodies.values()
    )
    if "tables" not in bodies and retired:
        # The old shape named the roster: `instruments: {<id>: {tables: ...}}`. The workspace has
        # one roster slot and stores no id, so that id was echoed back and discarded -- a
        # declaration syntax inviting something the product cannot hold. Refused outright rather
        # than accepted-and-ignored, because accepting it would be a compatibility shim for a
        # statement that was never true.
        #
        # Narrowed to the shape it names (one-shape campaign Step 5). It used to fire on any
        # document without a `tables` key, so a reader who typed `tabels:` was told to lift
        # `tables:` up one level -- advice for a mistake they had not made. Anything that is not
        # this shape now goes to the model below and is answered by the permitted key set.
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
        )
    try:
        declared = InstrumentsDeclaration.model_validate(bodies)
    except ValidationError as invalid:
        # The same door every other section's shape refusal comes out of, so a misspelled or
        # unknown key under `instruments:` names the permitted set instead of being answered by
        # the retired-shape refusal above.
        refusals_from(invalid, model=InstrumentsDeclaration, name=name).raise_if_failed()
        raise  # unreachable
    tables = declared.tables

    resolved = {
        str(kind): (base / str(raw_path)).resolve() for kind, raw_path in sorted(tables.items())
    }
    # The tables are read through the one door (record `234`); a table that cannot be read is
    # still an input refusal here, naming the file and what it lacks.
    diagnosis, rows = verify_roster(resolved)
    if not diagnosis.ok:
        first = diagnosis.failures[0]
        raise InputError(
            VALUE_INVALID,
            requirement=first.requirement,
            observed=first.observed or "",
            fix=first.fix,
            source=first.source,
        )
    digest = hashlib.sha256()
    for kind in sorted(resolved):
        # Digested over the file bytes, the same discipline `fingerprint_component` uses for a
        # user-authored component. Stated in the run record, never compared against it.
        digest.update(resolved[kind].read_bytes())

    try:
        roster = build_roster(rows)
    except ValueError as error:
        # The declared tables, so a reader knows WHICH file to open. The exporter guarantees a
        # clean table; a hand-written or hand-edited one is a legitimate input and arrives here
        # identically, and that is the case this refusal is for -- an unsupported `kind` in a row
        # never comes from `instruments.py`, only from editing its output or writing the parquet
        # directly. `build_roster` names the instrument; this names the files it came from.
        declared_files = ", ".join(f"{kind}={path.name}" for kind, path in sorted(resolved.items()))
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must describe every instrument exactly once, under its own kind",
            observed=f"{error} (declared tables: {declared_files})",
            fix=(
                "correct the instrument tables so each id appears once under a declared kind; "
                "re-running the emitted instruments.py produces a table that satisfies this"
            ),
        ) from error

    transaction.register_instruments(resolved, digest=digest.hexdigest())
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
    from vqapr.domain.instrument import InstrumentKind

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


def _resolved(declared: str, base: Path) -> Path:
    """A data or code path resolves against the declaration's directory when relative.

    One rule for every path in the file. A document that resolved code one way and data another
    would be portable only by accident.
    """
    path = Path(declared)
    return path if path.is_absolute() else base / path


def _dataset(
    dataset_id: str, body: object, *, base: Path
) -> tuple[DatasetRegistration, SourceSpec]:
    """A dataset and its source register together, so one declaration covers both.

    `register_dataset(registration, source)` takes them as a pair because a projection without the
    file it projects is not usable. A separate `sources:` section would let a document declare
    half of one.
    """
    name = f"datasets.{dataset_id}"
    model = declared(DatasetDeclaration, body, name=name)
    # After the model, so a declaration missing several keys hears all of them at once and
    # learns about `grain` -- which has its own sentence -- when the rest is in place.
    _require_grain_key(_mapping(body, name=name), name=name)
    try:
        registration = DatasetRegistration.of(
            dataset_id,
            model.source_id,
            instrument_field=model.instrument_field,
            available_at=model.available_at,
            key_fields=tuple(model.key_fields),
            fields=dict(model.fields),
            field_types=dict(model.field_types),
            grain=model.grain,
            execution=None if model.execution is None else model.execution.to_domain(),
        )
    except ValueError as error:
        # Two keys can object here, and each has its own sentence: `field_types` names a field
        # or a type, `grain` names the other keys it disagrees with.
        about_types = "field_types" in str(error)
        found = collector(Stage.REGISTER)
        found.add(
            Failure.bounded(
                "declaration.value_invalid",
                status=Status.INVALID,
                cause=error,
                requirement=(
                    f"{name}.field_types must give every field in {name}.fields one of "
                    f"{DECLARABLE_FIELD_TYPE_NAMES}, and nothing else"
                    if about_types
                    else f"{name} must declare a grain its other keys agree with"
                ),
                observed=str(error),
                source=_at(f"{name}.field_types" if about_types else f"{name}.grain"),
                fix=(
                    f"type every key of {name}.fields in {name}.field_types with a declarable "
                    "type; a DECIMAL column is cast to DOUBLE while preparing the source"
                    if about_types
                    else f"set {name}.grain to one of {GRAIN_NAMES} and make the other keys "
                    "match it"
                ),
            )
        )
        found.done().raise_if_failed()
        raise AssertionError("unreachable") from error
    source = SourceSpec.of(
        model.source_id, _resolved(model.path, base), hive_partitioned=model.hive_partitioned
    )
    return registration, source


def _enum[E: Enum](kind: type[E], value: object, *, name: str) -> E:
    """Read a declared enum value, or refuse by naming every member.

    A bare `Kind[value.upper()]` raises `KeyError`, which reaches the envelope as
    `stage:"unhandled"` with an empty `failures[]` and a traceback file. A reader who cannot see
    the member list then guesses, and guessing converges only when the field name happens to
    suggest the right vocabulary.

    Measured (on the since-retired `fill.selector`): a raw lookup sent a reader through six
    consecutive guesses at a vocabulary the field name argued against. No number of guesses
    reaches a closed set the reader cannot see, so the refusal has to carry the list.
    """
    try:
        return kind[str(value).upper()]
    except KeyError as unknown:
        permitted = ", ".join(member.name.lower() for member in kind)
        found = collector(Stage.REGISTER)
        found.add(
            Failure.bounded(
                "declaration.value_not_permitted",
                status=Status.INVALID,
                cause=unknown,
                requirement=f"{name} must be one of: {permitted}",
                observed=str(value),
                examples=[member.name.lower() for member in kind],
                source=_at(name),
                # Names the value actually written and the nearest legal one. Repeating the
                # permitted set with the verb swapped would say nothing `requirement` has not
                # already said, and a near-miss is usually a typo the reader cannot see.
                fix=_nearest_hint(str(value), [member.name.lower() for member in kind], name),
            )
        )
        found.done().raise_if_failed()
        raise  # unreachable: raise_if_failed always raises here


def _require_grain_key(body: dict[str, Any], *, name: str) -> None:
    """Refuse a dataset declaration without `grain`, naming the three values and what changed.

    Its own refusal rather than one line in `_require_keys`'s list, because this key carries a
    message the others do not: every registration written before `grain` existed is edited once
    to add it, and that edit is where the author learns `RowsLookback` means something else on a
    panel grain (design §2.4, §7-3).
    """
    raw = body.get("grain")
    if isinstance(raw, str) and raw in GRAIN_NAMES.split(", "):
        return
    found = collector(Stage.REGISTER)
    found.add(
        Failure.bounded(
            "declaration.grain_undeclared",
            status=Status.INVALID,
            requirement=f"{name} must declare grain, one of: {GRAIN_NAMES}",
            observed=("absent" if raw is None else repr(raw)),
            examples=GRAIN_NAMES.split(", "),
            source=_at(f"{name}.grain"),
            fix=(
                f"add `grain: <{GRAIN_NAMES}>` under {name}. instrument_instant: one value per "
                "(available_at, instrument), a panel can be built; instant: one value per "
                "available_at, no instrument axis; rows: the vendor's grain, unique on key_fields. "
                f"Note: {ROWS_LOOKBACK_MEANING}"
            ),
        )
    )
    found.done().raise_if_failed()


_DECLARED_IDS = {
    "datasets": ("dataset id", identifiers.dataset_id),
    "components": ("component id", identifiers.component_id),
}
"""Sections whose KEY becomes a typed identifier, and the constructor that judges it.

Every one of these refuses an empty string, one with surrounding whitespace, or one containing any
-- with a bare `ValueError`. For four of the five nothing caught it, so a blank or padded key in a
declaration reached the envelope as `stage:"unhandled"` with an empty `failures[]`: the framework
reporting itself broken over a fat-fingered YAML key. (`strategy_configs`, since retired by record
`148`, was the exception -- `Workspace.component()` already converted that `ValueError` into a
structured refusal.) The rule stays one rule: the key of every section listed becomes a typed
identifier, and every one of them is judged in the same place, at the same time, with the same
refusal naming the section it came from.

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
    found = collector(Stage.REGISTER)
    for key, (label, judge) in _DECLARED_IDS.items():
        for declared in section(key):
            raw = str(declared)
            try:
                judge(raw)
            except (TypeError, ValueError) as invalid:
                found.add(
                    Failure.bounded(
                        "declaration.value_invalid",
                        status=Status.INVALID,
                        cause=invalid,
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
                    )
                )
    found.done().raise_if_failed()


def _component(
    component_id: str, body: object, project_root: Path, transaction: Transaction, *, base: Path
) -> str:
    """Register one authored component through the door its kind declares.

    A relative path resolves against the **declaration's own directory**, not the process working
    directory, so a document sits beside the component it declares and stays portable. `vqapr new`
    emits exactly that shape: `path: my_alpha.py` next to `my_alpha.py`.
    """
    name = f"components.{component_id}"
    model = declared(ComponentDeclaration, body, name=name)
    ref = prepare_component(
        project_root,
        component_id,
        _resolved(model.path, base),
        model.object_name,
        kind=_COMPONENT_KINDS[model.kind],
        config=model.config,
    )
    transaction.register_component(ref)
    return str(ref.component_id)


class Registered(dict[str, list[str | dict[str, Any]]]):
    """What one declaration registered, by section -- a plain mapping to every caller that
    indexes it -- plus `spoken`, the point-in-time meaning of what was just declared, one
    sentence per PIT-bearing concept (`docs/issues/archive/027`). Rendered by `vqapr register` as
    `spoken`, beside `registered`. Every section lists ids; `instruments` lists the roster's
    per-category receipt instead."""

    spoken: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.spoken = []


def apply(
    document: dict[str, Any],
    project_root: Path,
    *,
    base: Path,
    declaration: Path | None = None,
) -> Registered:
    """Apply every section the document declares, in dependency order.

    Returns what was registered per section, so the reply states facts rather than a count.

    **One document, one write.** Every section is validated and staged against a snapshot of the
    workspace (or against nothing, in an empty directory), and the workspace is written once, at
    the end, under one lock. A document refused at its k-th item leaves the workspace exactly as it
    found it -- the testbed's A3, where a typo in item two left item one registered and the only
    recovery was deleting `.vqapr/`.

    `declaration` is the document's own path, and it is what every refusal below reports as
    `source.file`. It is optional because a caller may hold a parsed document with no file behind
    it; when it is absent the refusals say so rather than naming a path that does not exist.
    """
    token = _declaration_path.set(declaration)
    try:
        return _apply(document, project_root, base=base)
    finally:
        _declaration_path.reset(token)


def _apply(document: dict[str, Any], project_root: Path, *, base: Path) -> Registered:
    unknown = sorted(set(document) - set(SECTIONS))
    if unknown:
        # One refusal per unknown section, each pointing at its own key and each saying what to
        # write instead -- the same shape `refusals_from` gives an unknown key one level down. It
        # was one lumped refusal with no `source` and a `fix` that only repeated the names back,
        # so `dataset:` -- the typo this package's own test names -- was reported without ever
        # saying `datasets`.
        found = collector(Stage.REGISTER)
        for section_name in unknown:
            note, remedy = _SECTION_NOTES.get(section_name, ("", ""))
            found.add(
                Failure.bounded(
                    "declaration.unknown_section",
                    status=Status.INVALID,
                    requirement=f"a declaration may contain: {', '.join(SECTIONS)}",
                    observed=f"unknown section: {section_name}{note}",
                    examples=[section_name],
                    source=_at(section_name),
                    fix=remedy
                    or _nearest_hint(section_name, SECTIONS, section_name, removable=True).replace(
                        "set ", "rename ", 1
                    ),
                )
            )
        found.done().raise_if_failed()
    transaction = Workspace.transaction(project_root)
    registered = Registered()

    def section(key: str) -> dict[str, Any]:
        return _mapping(document.get(key) or {}, name=key)

    _require_declared_ids(section)

    instrument_bodies = section("instruments")
    if instrument_bodies:
        receipt = _instruments(instrument_bodies, transaction, base=base)
        registered.setdefault("instruments", []).append(receipt)

    for dataset_id, body in section("datasets").items():
        registration, source = _dataset(str(dataset_id), body, base=base)
        diagnosis, _, measured = verify_source(registration, source)
        diagnosis.raise_if_failed()
        transaction.register_dataset(measured, source)
        registered.setdefault("datasets", []).append(str(dataset_id))
        registered.spoken.extend(measured.spoken())

    for component_id, body in section("components").items():
        registered.setdefault("components", []).append(
            _component(str(component_id), body, project_root, transaction, base=base)
        )

    definitions: list[tuple[str, RunDefinition]] = []
    for run_id, body in section("runs").items():
        # Shape by the codec, so a run reads the same way from a declaration and from the
        # document; every id it names is checked against the staged workspace by the merge.
        name = f"runs.{run_id}"
        declared_run = _mapping(body, name=name)
        account = declared_run.get("initial_account")
        if isinstance(account, dict) and "mode" in account:
            # A closed set is the one case where a refusal can always be complete: the mode is
            # judged here so the refusal names every member and the nearest spelling
            # (`docs/issues/archive/017`), rather than surfacing from the model as one line of many.
            _enum(AccountMode, account["mode"], name=f"{name}.initial_account.mode")
        try:
            definition = RunDefinition.model_validate({"run_id": str(run_id), **declared_run})
        except (ValidationError, TypeError, ValueError) as invalid:
            observed = (
                "; ".join(
                    ".".join(str(part) for part in line["loc"])
                    + ": "
                    + str(line["msg"]).removeprefix("Value error, ")
                    for line in invalid.errors(include_url=False)
                )
                if isinstance(invalid, ValidationError)
                else str(invalid)
            )
            found = collector(Stage.REGISTER)
            found.add(
                Failure.bounded(
                    "declaration.run_invalid",
                    status=Status.INVALID,
                    cause=invalid,
                    requirement=(
                        "a run declares writes, and one strategy (with exchange, execution "
                        "{dataset, trade_price, fill?} and initial_account) or one datamodel "
                        "(with agenda.days_from), plus "
                        "instruments, start, end, timezone and agenda (every, at or from/to), "
                        "each in the shape `vqapr new run` emits"
                    ),
                    observed=observed,
                    examples=["2024-01-02T00:00:00+09:00"],
                    source=_at(name),
                    fix=f"correct `{name}` in the declaration, then register again",
                )
            )
            found.done().raise_if_failed()
            raise  # unreachable
        definitions.append((str(run_id), definition))

    _refuse_a_run_fed_by_a_sibling(definitions)
    for run_id, definition in definitions:
        transaction.register_run(definition)
        registered.setdefault("runs", []).append(run_id)
        registered.spoken.extend(definition.spoken())

    transaction.commit()
    return registered


def _refuse_a_run_fed_by_a_sibling(definitions: Sequence[tuple[str, RunDefinition]]) -> None:
    """A run whose trading days come from a dataset another run in this document will write.

    `inputs()` and `agenda.days_from` are resolved at registration, so a document holding two runs
    where the second takes its sessions from the first's output cannot be registered at all: the
    dataset does not exist until the first has run, and the first cannot run until the document is
    registered. The workspace refusal says only that the dataset is unregistered, and `vqapr new run
    --out` scaffolds a `runs:` block that holds several runs and invites exactly this. The reporter
    of `docs/issues/archive/084` split one file per run and lost ten minutes. This refusal can see
    the producer -- it is in the same document -- and names it.
    """
    produced: dict[str, str] = {}
    for run_id, definition in definitions:
        # Either kind: a strategy publishes its allocation under `writes` too (design §2).
        produced.setdefault(str(definition.writes), run_id)
    found = collector(Stage.REGISTER)
    for run_id, definition in definitions:
        wanted = definition.agenda.days_from
        producer = None if wanted is None else produced.get(str(wanted))
        if producer is None or producer == run_id:
            continue
        found.add(
            Failure.bounded(
                "declaration.run_fed_by_sibling",
                status=Status.INVALID,
                requirement=(
                    "a run that takes its trading days from a dataset must be registered after "
                    "that dataset exists"
                ),
                observed=(
                    f"run {run_id!r} takes its trading days from {wanted!r}, which run "
                    f"{producer!r} in this same document will write when it runs"
                ),
                source=_at(f"runs.{run_id}.agenda.days_from"),
                fix=(
                    f"split the document: register and run {producer!r} first, then register "
                    f"{run_id!r} from its own file once {wanted!r} exists"
                ),
            )
        )
    found.done().raise_if_failed()


def register_authored(
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
    # What held the id before this command, so the payload can say an edit REPLACED it
    # (`docs/issues/archive/067`): a plain re-register is the edit loop and refuses nothing, and the
    # old fingerprint is how the user learns which past run records are pinned to the code
    # they just moved away from. Read before the write; `Workspace.create` is what
    # `register_component` opens anyway, so this adds no state on a first registration.
    previous = {
        str(item.component_id): item for item in Workspace.create(project_root).components
    }.get(component_id)
    ref = register_component(
        project_root, component_id, path, object_name, kind=_COMPONENT_KINDS[kind]
    )
    # Returns data, not an envelope. Rendering belongs to the surface: this module is below it,
    # and importing `cli.envelope` from here is what closed an import cycle through the whole CLI.
    payload: dict[str, Any] = {
        "registered": {"components": [component_id]},
        "component": {
            "id": component_id,
            "kind": kind,
            "object": object_name,
            "source": str(path),
        },
    }
    if previous is not None and previous.fingerprint != ref.fingerprint:
        payload["replaced"] = {"fingerprint": previous.fingerprint}
    return payload


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
        ComponentKind.COMPLIANCE: "Compliance",
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
    local = {node.name for node in classes}
    if not found and any(_names(node) - aliases - local for node in classes):
        # A class whose base this file neither defines nor imports by the authoring name --
        # `class Leaf(common.Base)` -- may still be one. The YAML route loads the file and
        # registered it by the object while this said "defines 0" and asked for a class the file
        # already had (record `252`), so this route asks the object too, and only here: the parse
        # still decides "two". A base that does not import is refused as the loader refuses it.
        found = list(authored_classes(path, kind))
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
    "compliance": ComponentKind.COMPLIANCE,
}
"""The component kinds an author writes as a `.py` and registers directly.

Everything else -- datasets, sources, agendas, configs -- stays in the YAML declaration, because
those ARE declarations: there is no code to point at. A component is different. Its identity is
its source file, and requiring a YAML wrapper to say so made the author write the same fact twice
and kept a Python-authored strategy from being registered by naming it.
"""


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


# ---------------------------------------------------------------------------------------
# Registering one authored component, without a declaration document.
#
# Moved down from `extension/registration.py` by record `196`. `prepare_component` above is the
# half that can refuse and it stays in `extension/`; these are that plus one write, and the write
# is the workspace's. `register_authored` below already called `register_component` from here.
# ---------------------------------------------------------------------------------------


def register_component(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    kind: ComponentKind,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Prove the component conforms, then persist the reference.

    Nothing is written until conformance passes, so a workspace never holds a reference to a
    component Flow could not call.
    """
    ref = prepare_component(
        project_root, raw_component_id, path, object_name, kind=kind, config=config
    )
    with Workspace.transaction(project_root) as transaction:
        transaction.register_component(ref)
    return ref


def register_data_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local DataModel after proving it loads."""
    return register_component(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.DATA_MODEL,
        config=config,
    )


def register_strategy_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local StrategyModel after proving it loads."""
    return register_component(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.STRATEGY_MODEL,
        config=config,
    )


def register_compliance(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local Compliance rule after proving it loads.

    `load_compliance` checks the public Compliance contract, that the component declares its
    reads, and that it answers to the id it is registered under -- so a rule that cannot say what
    it reads, or is registered under the wrong name, is refused here rather than at the first
    market-clock instant that observes with it.
    """
    return register_component(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.COMPLIANCE,
        config=config,
    )


def register_exchange(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local Exchange after proving it loads.

    `load_exchange` is the strictest of the four: it requires one of the shipped execution
    profiles, refuses a subclass that replaces `execute()` -- whose realism claim would be
    unverified -- and requires the component to expose its own `ExchangeRulesView`. Registering
    through this door is what makes those checks happen before a run rather than during one.
    """
    return register_component(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.EXCHANGE,
        config=config,
    )
