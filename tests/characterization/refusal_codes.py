"""Static + runtime refusal-code inventory over `src/vqapr`.

This module is the collector behind Step 0.7 of the `Failure.bounded` migration: a baseline
captured **before** every call site is touched, so a later step's diff against it is meaningful.

Two independent passes, on purpose:

- **Static (AST) pass** walks every `.py` file under `src/vqapr` and resolves the `code` argument
  of every `Failure(...)` / `Failure.bounded(...)` construction. Codes are frequently composed at
  runtime as an f-string over a stage constant (`f"{DECLARE_STAGE}.key_missing"`), sometimes
  through one or two levels of local helper indirection (`materialize._error`, `workspace.
  _workspace_error`, `workspace._config_lookup` forwarding into `_workspace_error`), so a plain
  text/regex scan for string literals would silently miss most of the package's refusal
  vocabulary. This pass constant-folds those f-strings and follows parameter forwarding across
  calls within the same file instead of guessing.
- **Runtime pass** exercises refusal paths directly and records the `Failure.code` values a real
  `VqaprError`/`Diagnosis` actually produces. It is expected, and required, to reach *fewer* codes
  than the static pass — no test suite exhaustively drives every declared refusal, and the gap
  between "declared in source" and "observed under test" is exactly what this baseline exists to
  make visible rather than hide.

Neither pass may guess: an expression that cannot be resolved to one or more concrete string
values through constant folding and same-file call-site tracing is recorded as *unresolved* —
file, line, and the raw unparsed expression — never as a partial or wildcard code. Where a
parameter genuinely has more than one possible value across its call sites (e.g. `_config_lookup`'s
`stage` differs per caller, or a local ternary chooses between two literal suffixes), every
distinct resolved code is recorded — that is enumeration of real reachable values, not a guess.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "vqapr"
BASELINE_PATH = Path(__file__).resolve().with_name("refusal_codes.baseline.json")
SCHEMA = "vqapr.refusal_codes.v1"

_MAX_RESOLUTION_DEPTH = 6
"""Recursion bound across parameter-forwarding hops. The deepest real chain in this package is
two hops (`_config_lookup` -> `_workspace_error` -> `Failure.bounded`); this leaves headroom
without risking runaway recursion on a future accidental cycle."""


@dataclass(frozen=True, slots=True)
class StaticCode:
    code: str
    file: str
    line: int


@dataclass(frozen=True, slots=True)
class UnresolvedExpression:
    file: str
    line: int
    expression: str


@dataclass(frozen=True, slots=True)
class StaticInventory:
    codes: tuple[StaticCode, ...]
    unresolved: tuple[UnresolvedExpression, ...]


# --------------------------------------------------------------------------------------------
# Pass 1 — AST extraction with interprocedural constant folding.
# --------------------------------------------------------------------------------------------


class _FileIndex:
    """Everything needed to resolve names and forwarded parameters within one module.

    Built once per file, then reused for every `Failure` construction found in it. `parents` and
    `enclosing_function` let the resolver ask "which function scope owns this expression" without
    re-walking the tree for every query; `functions_by_name` and `calls_by_target` let it answer
    "who calls this function, and with what argument for this parameter" — the two questions a
    forwarded `code`/`stage` parameter needs answered before it can be folded into a literal.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.module_constants = _module_string_constants(tree)
        self.parents: dict[int, ast.AST] = {}
        self.functions_by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        self.calls_by_target: dict[str, list[ast.Call]] = {}
        self._index(tree, None)

    def _index(self, node: ast.AST, parent: ast.AST | None) -> None:
        if parent is not None:
            self.parents[id(node)] = parent
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.functions_by_name.setdefault(node.name, []).append(node)
        if isinstance(node, ast.Call):
            target_name = _call_target_name(node.func)
            if target_name is not None:
                self.calls_by_target.setdefault(target_name, []).append(node)
        for child in ast.iter_child_nodes(node):
            self._index(child, node)

    def enclosing_function(self, node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        current = self.parents.get(id(node))
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
            current = self.parents.get(id(current))
        return None


def _call_target_name(func: ast.expr) -> str | None:
    """The plain name a call resolves to, for matching against `functions_by_name`.

    `obj.method(...)` and a bare `name(...)` both resolve by the trailing identifier. This
    over-matches if two unrelated functions in the same file share a name (e.g. two different
    classes' same-named method), which this package does not do for the refusal-construction
    helpers this resolver cares about; a spurious match would only ever add a *false* candidate
    value to a code, which the unresolved/orphan tests below would catch, never hide.
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, for folding `f"{NAME}.suffix"` codes.

    Only direct children of the module body count — a constant reassigned inside a function or
    class is a different binding and must not be treated as the module-wide stage name.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Every parameter name in call order: positional-or-keyword, then keyword-only."""
    args = func.args
    return [param.arg for param in (*args.posonlyargs, *args.args)] + [
        param.arg for param in args.kwonlyargs
    ]


def _param_default(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> ast.expr | None:
    """The default expression for one parameter, or `None` if it has none."""
    args = func.args
    positional = [*args.posonlyargs, *args.args]
    if name in [p.arg for p in positional]:
        index = [p.arg for p in positional].index(name)
        defaults = args.defaults
        offset = len(positional) - len(defaults)
        if index >= offset:
            return defaults[index - offset]
        return None
    if name in [p.arg for p in args.kwonlyargs]:
        index = [p.arg for p in args.kwonlyargs].index(name)
        default = args.kw_defaults[index]
        return default
    return None


def _argument_for_param(
    call: ast.Call, func: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> ast.expr | None:
    """The expression a call site passed for parameter `name`, by keyword or by position."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    order = _param_names(func)
    args = call.args
    # Drop a leading `self`/`cls` from a bound-method call target's own signature so positional
    # indices line up with the call site, which never passes `self` explicitly.
    if order and order[0] in ("self", "cls") and not (isinstance(call.func, ast.Name)):
        order = order[1:]
    if name not in order:
        return None
    index = order.index(name)
    if index < len(args):
        return args[index]
    return None


def _fold_local_assignments(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    index: _FileIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Every value `name` is assigned within `func`'s own body (not a nested function), folded.

    Handles the one shape this package actually uses beyond a bare literal: a two-branch ternary
    selecting between two string literals (`data/datasets.py`'s `suffix`). Both branches are
    genuinely reachable, so both are returned rather than picking one.
    """
    values: set[str] = set()
    found = False
    for node in ast.walk(func):
        if node is func:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a nested scope's local assignment is not this function's binding
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            continue
        found = True
        resolved = _resolve_expr(node.value, func, index, visited)
        if resolved is None:
            return None
        values.update(resolved)
    return values if found else None


def _resolve_name(
    name: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _FileIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Every concrete string value `name` may hold at the point it is referenced.

    Resolution order: a local assignment inside `func` wins first (it shadows everything outer),
    then a module-level constant, then — only if `name` is one of `func`'s own parameters — the
    default value and every value passed for it across `func`'s call sites in this file. The last
    step is the interprocedural hop that lets a forwarded `stage`/`code` parameter resolve to the
    concrete constants its various callers actually pass.
    """
    if func is not None:
        local = _fold_local_assignments(func, name, index, visited)
        if local is not None:
            return local
    if name in index.module_constants:
        return {index.module_constants[name]}
    if func is None or name not in _param_names(func):
        return None
    return _resolve_parameter(func, name, index, visited)


def _resolve_parameter(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    index: _FileIndex,
    visited: frozenset[int],
) -> set[str] | None:
    key = (id(func), name)
    if key in visited or len(visited) >= _MAX_RESOLUTION_DEPTH:
        return None  # a cycle or runaway chain — resolve nothing rather than loop or guess
    next_visited = visited | {key}

    values: set[str] = set()
    default = _param_default(func, name)
    if default is not None:
        resolved_default = _resolve_expr(default, func, index, next_visited)
        if resolved_default is not None:
            values.update(resolved_default)

    for call in index.calls_by_target.get(func.name, ()):
        argument = _argument_for_param(call, func, name)
        if argument is None:
            continue
        caller_func = index.enclosing_function(call)
        resolved = _resolve_expr(argument, caller_func, index, next_visited)
        if resolved is None:
            return None
        values.update(resolved)

    return values or None


def _resolve_expr(
    expr: ast.expr,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _FileIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Every concrete string value `expr` may evaluate to, or `None` if it cannot be folded."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.Name):
        return _resolve_name(expr.id, func, index, visited)
    if isinstance(expr, ast.IfExp):
        body = _resolve_expr(expr.body, func, index, visited)
        orelse = _resolve_expr(expr.orelse, func, index, visited)
        if body is None or orelse is None:
            return None
        return body | orelse
    if isinstance(expr, ast.JoinedStr):
        return _resolve_joined_str(expr, func, index, visited)
    return None


def _resolve_joined_str(
    expr: ast.JoinedStr,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _FileIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Cartesian-fold an f-string: each literal segment is fixed, each interpolation may carry
    more than one possible value, and every combination is a genuinely reachable code."""
    combinations: set[str] = {""}
    for value in expr.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            combinations = {prefix + value.value for prefix in combinations}
            continue
        if (
            isinstance(value, ast.FormattedValue)
            and value.format_spec is None
            and value.conversion == -1
        ):
            resolved = _resolve_expr(value.value, func, index, visited)
            if resolved is None:
                return None
            combinations = {prefix + suffix for prefix in combinations for suffix in resolved}
            continue
        return None
    return combinations


def _is_failure_construction(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "Failure"
    if isinstance(func, ast.Attribute):
        return (
            func.attr == "bounded"
            and isinstance(func.value, ast.Name)
            and func.value.id == "Failure"
        )
    return False


def _code_argument(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "code":
            return keyword.value
    return None


def _scan_file(path: Path) -> tuple[list[StaticCode], list[UnresolvedExpression]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    index = _FileIndex(tree)
    relative = path.relative_to(REPO_ROOT).as_posix()

    codes: list[StaticCode] = []
    unresolved: list[UnresolvedExpression] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_failure_construction(node.func):
            continue
        argument = _code_argument(node)
        if argument is None:
            # `Failure(...)`/`Failure.bounded(...)` always requires `code`; a call site missing
            # it is not a valid construction and would fail at runtime, not at this inventory.
            continue
        enclosing = index.enclosing_function(node)
        resolved = _resolve_expr(argument, enclosing, index, frozenset())
        if resolved is None:
            unresolved.append(
                UnresolvedExpression(
                    file=relative, line=argument.lineno, expression=ast.unparse(argument)
                )
            )
        else:
            for code in resolved:
                codes.append(StaticCode(code=code, file=relative, line=argument.lineno))
    return codes, unresolved


def _source_files() -> Iterator[Path]:
    yield from sorted(PACKAGE_ROOT.rglob("*.py"))


def collect_static() -> StaticInventory:
    """Pass 1 — AST walk with interprocedural constant folding over every module under
    `src/vqapr`."""
    codes: list[StaticCode] = []
    unresolved: list[UnresolvedExpression] = []
    for path in _source_files():
        file_codes, file_unresolved = _scan_file(path)
        codes.extend(file_codes)
        unresolved.extend(file_unresolved)
    codes.sort(key=lambda entry: (entry.code, entry.file, entry.line))
    unresolved.sort(key=lambda entry: (entry.file, entry.line))
    return StaticInventory(codes=tuple(codes), unresolved=tuple(unresolved))


# --------------------------------------------------------------------------------------------
# Pass 2 — runtime collection.
#
# Each `_runtime_*` function exercises one refusal path to completion and returns the `Failure`
# codes it actually produced. Every scenario is self-contained (its own tmp directory, its own
# parquet fixtures via duckdb) so this module can run standalone under `python -m` as well as
# under pytest, without depending on pytest-only fixtures from `tests/conftest.py`.
# --------------------------------------------------------------------------------------------


def _with_span(registration):
    """Attach a span so a scenario reaches the refusal it is collecting.

    Persistence requires a measured span, so a span-less registration stops at
    `dataset.register.span.absent` before reaching the conflict or lookup codes these scenarios
    exist to observe. The value is irrelevant to those codes; only its presence is.
    """
    from datetime import UTC, datetime

    return registration.with_span(
        datetime(2024, 3, 5, tzinfo=UTC), datetime(2024, 3, 6, tzinfo=UTC)
    )


def _write_parquet(path: Path, rows_sql: str) -> Path:
    import duckdb

    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows_sql}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _runtime_dataset_schema_and_key(tmp_path: Path) -> list[str]:
    from vqapr.data.datasets import DatasetRegistration, validate
    from vqapr.data.sources import SourceSpec
    from vqapr.domain.errors import VqaprError

    codes: list[str] = []

    naive = _write_parquet(
        tmp_path / "naive.parquet",
        "SELECT TIMESTAMP '2024-03-05 03:00:00' AS available_at, 'A' AS instrument, 100.0 AS close",
    )
    registration = DatasetRegistration.of(
        "price_daily",
        "s",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "missing_col": "does_not_exist"},
    )
    diagnosis, _, _measured = validate(registration, SourceSpec.of("s", naive))
    codes.extend(failure.code for failure in diagnosis.failures)

    dup = _write_parquet(
        tmp_path / "dup.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 999.0),
             (TIMESTAMPTZ '2024-03-06 03:00:00+09', NULL, 1.0)
           ) AS t(available_at, instrument, close)""",
    )
    clean_registration = DatasetRegistration.of(
        "price_daily",
        "s",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    )
    diagnosis, _, _measured = validate(clean_registration, SourceSpec.of("s", dup))
    codes.extend(failure.code for failure in diagnosis.failures)

    mismatched = DatasetRegistration.of(
        "price_daily", "other-source", instrument_field="instrument",
        available_at="available_at", key_fields=("instrument",), fields={"close": "close"},
    )
    diagnosis, _, _measured = validate(mismatched, SourceSpec.of("s", dup))
    codes.extend(failure.code for failure in diagnosis.failures)

    try:
        from vqapr.data import scan

        scan.describe(SourceSpec.of("s", tmp_path / "does-not-exist.parquet"))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    return codes


def _runtime_execution_input(tmp_path: Path) -> list[str]:
    from vqapr.data.sources import SourceSpec
    from vqapr.exchange.conventions import FillConvention, FillSelector
    from vqapr.exchange.execution_table import (
        ExecutionInputRegistration,
        ExecutionTableSpec,
        validate_execution_input,
    )

    codes: list[str] = []

    def _registration(path: Path) -> ExecutionInputRegistration:
        return ExecutionInputRegistration.of(
            "krx-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("krx-execution", path),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"open": "open", "close": "close"},
            ),
            FillConvention(
                selector=FillSelector.SAME_DAY,
                local_time=__import__("datetime").time(15, 30),
                timezone="Asia/Seoul",
                trade_price="close",
            ),
        )

    bad_types = _write_parquet(
        tmp_path / "bad-types.parquet",
        """SELECT TIMESTAMP '2024-03-05 15:30:00' AS trade_at, 1 AS instrument,
                  'yes' AS is_tradable, 'nope' AS open, 'nope' AS close""",
    )
    diagnosis = validate_execution_input(_registration(bad_types))
    codes.extend(failure.code for failure in diagnosis.failures)

    dup_null = _write_parquet(
        tmp_path / "dup-null.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
             (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0, 100.0),
             (TIMESTAMPTZ '2024-03-06 15:30:00+09', NULL, true, 1.0, 1.0)
           ) AS t(trade_at, instrument, is_tradable, open, close)""",
    )
    diagnosis = validate_execution_input(_registration(dup_null))
    codes.extend(failure.code for failure in diagnosis.failures)

    bad_price = _write_parquet(
        tmp_path / "bad-price.parquet",
        """SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at, 'A' AS instrument,
                  true AS is_tradable, 99.0 AS open, 0.0 AS close""",
    )
    diagnosis = validate_execution_input(_registration(bad_price))
    codes.extend(failure.code for failure in diagnosis.failures)

    return codes


def _runtime_conformance_and_loading(tmp_path: Path) -> list[str]:
    from vqapr.domain.errors import VqaprError
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.public import register_constraint
    from vqapr.testing.conformance import conformance

    codes: list[str] = []

    good = textwrap.dedent(
        """
        from vqapr.public import Constraint, ConstraintBounds

        class Limit(Constraint):
            @property
            def constraint_id(self):
                return "limit"

            def requirements(self):
                return ()

            def project(self, window, instruments):
                return ConstraintBounds({}, {})

            def validate_intended(self, intent, bounds):
                return None

            def evaluate(self, window, account, marks, bounds):
                return None
        """
    )
    stale = good.replace(
        "def evaluate(self, window, account, marks, bounds):", "def evaluate(self, account, marks):"
    )
    missing = good.replace("def project(self, window, instruments):", "def unused(self):")
    broken = "class Limit:\n    pass\n"

    def _ref(source: str, name: str, *, component_id: str | None = None) -> ComponentRef:
        # The filename and the registered id are separate arguments on purpose. `load_constraint`
        # refuses a Constraint registered under an id its own `constraint_id` does not return, and
        # every source below derives from `good`, whose `constraint_id` is `limit`. Registering
        # them as `stale`/`missing` would trip that identity refusal FIRST, and because
        # `conformance` folds a loader exception into its collector and returns before
        # `_check_methods` runs, the defect each fixture exists to provoke would never be reached.
        # This harness's output is the oracle, so a fixture that silently stops provoking its own
        # defect rewrites the ground truth rather than failing -- exactly what `regenerate`'s
        # docstring forbids.
        path = tmp_path / f"{name}.py"
        path.write_text(source, encoding="utf-8")
        return ComponentRef.of(
            component_id or name,
            ComponentKind.CONSTRAINT,
            path,
            "Limit",
            fingerprint=fingerprint_component(
                path, kind=ComponentKind.CONSTRAINT, object_name="Limit"
            ),
        )

    for source, name, component_id in (
        (stale, "stale", "limit"),
        (missing, "missing", "limit"),
        (broken, "broken", None),
        # And one that IS the identity mismatch, so the refusal is characterized rather than only
        # declared. `good` answers to `limit`; registering it as `mislabelled` is the reported
        # defect in one line.
        (good, "mislabelled", None),
    ):
        diagnosis = conformance(_ref(source, name, component_id=component_id))
        codes.extend(failure.code for failure in diagnosis.failures)

    try:
        register_constraint(tmp_path, "again", tmp_path / "does-not-exist.py", "Limit")
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)
    except OSError:
        pass

    return codes


def _runtime_declaration_read(tmp_path: Path) -> list[str]:
    from vqapr.cli.register import apply
    from vqapr.domain.errors import VqaprError

    scenarios: list[dict] = [
        {"datasets": {"prices": {"source_id": "s", "path": "p.parquet"}}},
        {
            "agendas": {
                "alpha": {"role": "strategy_callback", "at": "15:30", "timezone": "Asia/Seoul"}
            }
        },
        {"components": {"c": {"kind": "model", "path": "p.py", "object_name": "X"}}},
        {
            "agendas": {
                "alpha": {
                    "role": "strategy_callback",
                    "at": "15:30",
                    "timezone": "Asia/Seoul",
                    "sessions": "nope",
                }
            }
        },
        {"unknown_section_here": {}},
    ]
    codes: list[str] = []
    for index, document in enumerate(scenarios):
        try:
            apply(document, tmp_path, base=tmp_path / f"scenario-{index}")
        except VqaprError as error:
            codes.extend(failure.code for failure in error.failures)
    return codes


def _runtime_workspace(tmp_path: Path) -> list[str]:
    from vqapr.data.datasets import DatasetRegistration
    from vqapr.data.sources import SourceSpec
    from vqapr.domain.errors import VqaprError
    from vqapr.workspace import Workspace

    codes: list[str] = []
    workspace = Workspace.create(tmp_path)

    try:
        workspace.dataset("")
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)
    try:
        workspace.dataset("does-not-exist")
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    prices = _write_parquet(
        tmp_path / "prices.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, "
        "'A' AS instrument, 1.0 AS close",
    )
    registration = _with_span(
        DatasetRegistration.of(
            "prices", "s", instrument_field="instrument", available_at="available_at",
            key_fields=("available_at", "instrument"), fields={"close": "close"},
        )
    )
    workspace.register_dataset(registration, SourceSpec.of("s", prices))

    other = _write_parquet(
        tmp_path / "other.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, "
        "'B' AS instrument, 2.0 AS close",
    )
    conflicting = _with_span(
        DatasetRegistration.of(
            "prices", "s", instrument_field="instrument", available_at="available_at",
            key_fields=("instrument",), fields={"close": "close"},
        )
    )
    try:
        workspace.register_dataset(conflicting, SourceSpec.of("s", prices))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    try:
        workspace.register_dataset(registration, SourceSpec.of("s", other))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    try:
        workspace.strategy_config("does-not-exist")
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    return codes


def _runtime_model_window(tmp_path: Path) -> list[str]:
    from datetime import UTC, datetime

    from vqapr.data.datasets import DatasetRegistration
    from vqapr.data.lookback import RowsLookback
    from vqapr.data.requirements import DataRequirement
    from vqapr.data.sources import SourceSpec
    from vqapr.data.store import DuckDbObservationStore
    from vqapr.data.windows import ModelWindow
    from vqapr.domain.errors import VqaprError
    from vqapr.workspace import Workspace

    workspace = Workspace.create(tmp_path)
    prices = _write_parquet(
        tmp_path / "prices.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, "
        "'A' AS instrument, 1.0 AS close",
    )
    workspace.register_dataset(
        _with_span(
            DatasetRegistration.of(
                "prices", "s", instrument_field="instrument", available_at="available_at",
                key_fields=("available_at", "instrument"), fields={"close": "close"},
            )
        ),
        SourceSpec.of("s", prices),
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 12, tzinfo=UTC),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(),
    )
    undeclared = DataRequirement.of(
        "consumer", "prices", fields=("close",), lookback=RowsLookback(1)
    )
    codes: list[str] = []
    try:
        window.observations(undeclared)
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)
    return codes


_RUNTIME_SCENARIOS = (
    _runtime_dataset_schema_and_key,
    _runtime_execution_input,
    _runtime_conformance_and_loading,
    _runtime_declaration_read,
    _runtime_workspace,
    _runtime_model_window,
)


def collect_runtime() -> tuple[str, ...]:
    """Pass 2 — exercise refusal paths and record the codes real `Failure`s carried.

    Every scenario runs in isolation and any scenario that cannot complete (e.g. an API this
    baseline's author read wrong) is skipped rather than aborting the whole pass, because a
    partial runtime pass is still evidence and a crashed one is none.
    """
    codes: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="vqapr-refusal-inventory-") as raw_root:
        root = Path(raw_root)
        for index, scenario in enumerate(_RUNTIME_SCENARIOS):
            scenario_dir = root / f"scenario-{index}-{scenario.__name__}"
            scenario_dir.mkdir(parents=True, exist_ok=True)
            try:
                codes.update(scenario(scenario_dir))
            except Exception:
                # A failed scenario must not blank the whole pass; a partial runtime pass is
                # still evidence and a crashed one is none.
                continue
    return tuple(sorted(codes))


def build_report() -> dict:
    """Assemble the full deterministic baseline document."""
    static = collect_static()
    runtime_codes = collect_runtime()
    static_code_set = {entry.code for entry in static.codes}
    coverage_gap = sorted(static_code_set - set(runtime_codes))
    return {
        "schema": SCHEMA,
        "static_codes": [
            {"code": entry.code, "file": entry.file, "line": entry.line} for entry in static.codes
        ],
        "runtime_codes": list(runtime_codes),
        "coverage_gap": coverage_gap,
        "unresolved": [
            {"file": entry.file, "line": entry.line, "expression": entry.expression}
            for entry in static.unresolved
        ],
    }


def regenerate(path: Path = BASELINE_PATH) -> None:
    """Write the baseline document deterministically. This is the only writer of `path`.

    Called only from `python -m tests.characterization.refusal_codes` — never from a normal test
    run, because a gate that rewrites its own oracle whenever it disagrees with it is not a gate.
    """
    report = build_report()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    regenerate()
    sys.stdout.write(f"wrote {BASELINE_PATH.relative_to(REPO_ROOT)}\n")
