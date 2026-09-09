"""Static + runtime refusal-code inventory over `src/vqapr`, bucketed by `Status`.

The baseline this module writes is the oracle `test_refusal_codes.py` diffs the source against:
which refusal codes the package declares, and under which `Status` each one is raised. Record
`171` slimmed it to exactly that -- **sets of codes per status, no file and no line per code** --
because the earlier per-call-site shape fired on every docstring edit above a raise site and was
regenerated past rather than read.

Two independent passes, on purpose:

- **Static (AST) pass** walks every `.py` file under `src/vqapr` and resolves, for every
  `Failure(...)` / `Failure.bounded(...)` construction, the `code` argument and the `status=`
  keyword. Codes are sometimes composed as an f-string over a module constant
  (`f"{SUBJECT}.key_missing"`), sometimes forwarded through a local helper (`workspace.
  _workspace_error`, `loading._failure`), so a plain text/regex scan for string literals would
  miss part of the vocabulary. This pass constant-folds those f-strings and follows parameter
  forwarding across call sites instead of guessing, for `code` and `status` alike -- across the
  whole package, because a refusal helper and its callers need not share a file
  (`flow/datamodel/compute.py` raises through `flow/datamodel/output.py`'s `refusal`), and an
  index that stopped at the file boundary silently dropped a code whenever a module was split.
  A `status` that is a `Status` member (the case at almost every site) buckets the code
  under that member's number; a `status` computed from an exception (`status_of(error)`, a
  variable holding one) buckets it under `by_cause`, because the number is decided at runtime by
  whose frame raised.
- **Runtime pass** exercises refusal paths directly and records the `Failure.code` values a real
  `VqaprError`/`Diagnosis` actually produces. It is expected, and required, to reach *fewer* codes
  than the static pass -- no test suite exhaustively drives every declared refusal, and the gap
  between "declared in source" and "observed under test" is exactly what this baseline exists to
  make visible rather than hide.

Neither pass may guess: a `code` expression that cannot be resolved to one or more concrete
string values through constant folding and call-site tracing is recorded as *unresolved* --
file, line, and the raw unparsed expression -- never as a partial or wildcard code.
Where a parameter genuinely has more than one possible value across its call sites, every distinct
resolved code is recorded -- that is enumeration of real reachable values, not a guess.

One shape is neither declared nor unresolved: a **re-render**. `InputError.as_failure` builds a
`Failure(code=self.code, ...)` from a refusal it already holds, and `SimulationFailure` builds one
whose code a same-file helper renders from the `SimulationStage` the object carries
(`strategy.callback.intent`, ...). Those sites do not declare a code the folder could name; the
first was declared where the refusal was first raised and the static pass saw it there, and the
second is the closed `SimulationStage` set the skill documents as `strategy.<stage>`. They are
skipped, and `_is_rerender` says exactly which shapes count. The `strategy.*` family is therefore
absent from `static` by construction, not by omission.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import textwrap
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "vqapr"
ERRORS_MODULE = PACKAGE_ROOT / "domain" / "errors.py"
BASELINE_PATH = Path(__file__).resolve().with_name("refusal_codes.baseline.json")
SCHEMA = "vqapr.refusal_codes.v2"

BY_CAUSE = "by_cause"
"""The bucket for a code whose status is decided at runtime from the exception's traceback
(`status_of(error)`): 500 or 502, and the source cannot say which."""

_MAX_RESOLUTION_DEPTH = 6
"""Recursion bound across parameter-forwarding hops. The deepest real chain in this package is
two hops (`_config_lookup` -> `_workspace_error` -> `Failure.bounded`); this leaves headroom
without risking runaway recursion on a future accidental cycle."""

_STATUS_PREFIX = "Status."
"""How a resolved `Status.MISSING` travels through the string-valued resolver: as the token
`"Status.MISSING"`, which `_bucket_of` turns into the member's number."""


@dataclass(frozen=True, slots=True)
class StaticCode:
    code: str
    bucket: str
    """A `Status` number as a string (`"404"`), or `BY_CAUSE`."""


@dataclass(frozen=True, slots=True)
class UnresolvedExpression:
    file: str
    line: int
    expression: str


@dataclass(frozen=True, slots=True)
class StaticInventory:
    codes: tuple[StaticCode, ...]
    unresolved: tuple[UnresolvedExpression, ...]


def status_members() -> dict[str, int]:
    """`Status` member name -> number, read from `domain/errors.py`'s source rather than imported.

    This scanner runs while raise sites are mid-migration and the package may not import; the
    enum's members are declared as plain `NAME = <int>` assignments, so the AST is the same
    closed set the interpreter would see.
    """
    tree = ast.parse(ERRORS_MODULE.read_text(encoding="utf-8"), filename=str(ERRORS_MODULE))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Status":
            members: dict[str, int] = {}
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, int)
                ):
                    members[statement.targets[0].id] = statement.value.value
            if not members:
                raise ValueError(f"{ERRORS_MODULE}: class Status declares no integer members")
            return members
    raise ValueError(f"{ERRORS_MODULE}: no class Status found")


# --------------------------------------------------------------------------------------------
# Pass 1 — AST extraction with interprocedural constant folding.
# --------------------------------------------------------------------------------------------


class _SourceIndex:
    """Everything needed to resolve names and forwarded parameters across a set of modules.

    Built once over *every* module under `src/vqapr`, then reused for every `Failure` construction
    found in any of them. `parents` and `enclosing_function` let the resolver ask "which function
    scope owns this expression" without re-walking the tree for every query; `functions_by_name`
    and `calls_by_target` let it answer "who calls this function, and with what argument for this
    parameter" — the two questions a forwarded `code`/`stage` parameter needs answered before it
    can be folded into a literal.

    Those two are merged across modules on purpose. A per-file index only ever resolved a code
    forwarded through a helper defined in the same file, so splitting a module dropped codes from
    the inventory without any refusal changing: `flow/datamodel/compute.py` raises through the
    `refusal` helper `flow/datamodel/output.py` defines, and `datamodel.compute_failed` vanished
    from the static pass the moment the two stopped sharing a file. A refusal helper is not
    required to live beside its callers, so neither is this index.

    Module-level constants are the one thing that must **not** merge. `NAME = "..."` is a per-file
    binding: two modules may legitimately bind the same name to different strings, and a name that
    is a module constant in one module is often an ordinary parameter in another. A merged mapping
    would fold a code to a stranger's value, or (via `_is_forwarded`) refuse to follow a parameter
    that was forwarding one — both worse than not resolving at all, because both are silent. They
    are kept per module and looked up through the module that owns the node being resolved.

    The trees are held for the index's lifetime because `parents` is keyed by `id(node)`: a
    collected tree could see its ids reused by a later one and cross-wire two files' scopes.
    """

    def __init__(self, trees: Sequence[ast.Module]) -> None:
        self._trees = tuple(trees)
        self._constants_by_module: dict[int, dict[str, str]] = {}
        self.parents: dict[int, ast.AST] = {}
        self.functions_by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        self.calls_by_target: dict[str, list[ast.Call]] = {}
        for tree in self._trees:
            self._constants_by_module[id(tree)] = _module_string_constants(tree)
            self._index(tree, None)

    def module_constants(self, node: ast.AST) -> dict[str, str]:
        """The module-level string constants of the file that owns `node`, and no other file's.

        Walking `parents` to the root reaches the `ast.Module` the node was parsed from, which is
        the only file whose module scope that node can see.
        """
        root = node
        while (parent := self.parents.get(id(root))) is not None:
            root = parent
        return self._constants_by_module.get(id(root), {})

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
    over-matches if two unrelated functions share a name (e.g. two different classes' same-named
    method) -- package-wide since the index spans every module, not only within one file. The
    package does not do that for the refusal-construction helpers this resolver cares about, and
    a spurious match would only ever add a *false* candidate value to a code, which the baseline
    gate would show as a gained code rather than hide.
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
    index: _SourceIndex,
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
    reference: ast.Name,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _SourceIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Every concrete string value the name `reference` may hold at the point it is referenced.

    Resolution order: a local assignment inside `func` wins first (it shadows everything outer),
    then a module-level constant of the module the reference is written in, then — only if the
    name is one of `func`'s own parameters — the default value and every value passed for it
    across `func`'s call sites. The last step is the interprocedural hop that lets a forwarded
    `stage`/`code` parameter resolve to the concrete constants its various callers actually pass.

    The node itself, not just its name, is what arrives here: a module constant is scoped to the
    file that binds it, and `index.module_constants` needs the reference to find that file.
    """
    name = reference.id
    if func is not None:
        local = _fold_local_assignments(func, name, index, visited)
        if local is not None:
            return local
    constants = index.module_constants(reference)
    if name in constants:
        return {constants[name]}
    if func is None or name not in _param_names(func):
        return None
    return _resolve_parameter(func, name, index, visited)


def _resolve_parameter(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    index: _SourceIndex,
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
    index: _SourceIndex,
    visited: frozenset[int],
) -> set[str] | None:
    """Every concrete string value `expr` may evaluate to, or `None` if it cannot be folded."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.Name):
        return _resolve_name(expr, func, index, visited)
    if (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "Status"
    ):
        # `Status.MISSING`: the one attribute shape the resolver folds, carried as a token so a
        # forwarded `status` parameter resolves through the same machinery as a forwarded code.
        return {_STATUS_PREFIX + expr.attr}
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
    index: _SourceIndex,
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


def _status_argument(call: ast.Call) -> ast.expr | None:
    """`status` is keyword-only on both constructors, so there is no positional form to find."""
    for keyword in call.keywords:
        if keyword.arg == "status":
            return keyword.value
    return None


def _is_owned_attribute(
    expr: ast.expr, func: ast.FunctionDef | ast.AsyncFunctionDef | None
) -> bool:
    """`self.code`, `self.stage.value`, `error.code`: an attribute chain rooted in `self` or in
    one of the enclosing function's parameters -- a value the site was handed, not one it made."""
    root = expr
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    if root.id == "self":
        return True
    return func is not None and root.id in _param_names(func)


def _is_exception_type_name(expr: ast.expr) -> bool:
    """`type(cause).__name__`: the exception's class name, which is whatever was raised."""
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "__name__"
        and isinstance(expr.value, ast.Call)
        and isinstance(expr.value.func, ast.Name)
        and expr.value.func.id == "type"
    )


def _is_rerender(
    expr: ast.expr, func: ast.FunctionDef | ast.AsyncFunctionDef | None, index: _SourceIndex
) -> bool:
    """A `code` that re-renders what the site already holds, rather than declaring a new one.

    Three shapes, all exact: an attribute the site was handed (`code=self.code` in
    `InputError.as_failure`); an f-string whose every interpolation is such an attribute or an
    exception's type name (`f"{self.stage.value}.{type(cause).__name__}"`, the older
    `SimulationFailure`); or a helper the index knows, called with nothing but those
    (`_code_for(self.stage)`, today's `SimulationFailure`, which renders `strategy.<stage>` from a
    `SimulationStage` the object carries). Anything with a literal interpolation source, a module
    constant or a folded parameter is a declaration and never reaches this check, because
    `_resolve_expr` folded it first.
    """
    if isinstance(expr, ast.Attribute):
        return _is_owned_attribute(expr, func)
    if isinstance(expr, ast.JoinedStr):
        interpolations = [v.value for v in expr.values if isinstance(v, ast.FormattedValue)]
        return bool(interpolations) and all(
            _is_owned_attribute(value, func) or _is_exception_type_name(value)
            for value in interpolations
        )
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in index.functions_by_name
    ):
        operands = [*expr.args, *(keyword.value for keyword in expr.keywords)]
        return bool(operands) and all(
            _is_owned_attribute(operand, func) or _is_exception_type_name(operand)
            for operand in operands
        )
    return False


def _bucket_of(token: str, members: dict[str, int]) -> str | None:
    """The baseline bucket a resolved `status` token lands in; `None` for a name `Status` lacks."""
    if not token.startswith(_STATUS_PREFIX):
        return None
    name = token[len(_STATUS_PREFIX) :]
    number = members.get(name)
    return None if number is None else str(number)


def _scan_file(
    path: Path, members: dict[str, int], *, probes: Sequence[Path] = ()
) -> tuple[list[StaticCode], list[UnresolvedExpression]]:
    """Scan one file standalone, resolving through `probes` as well as through itself.

    The scanner's own tests call this on a probe module outside the repo; `probes` lets such a
    test put the helper in one file and its callers in another, the way `collect_static` sees the
    package. Every finding is still reported against `path`, so an unresolved entry keeps pointing
    at the line that produced it.
    """
    trees = {p: _parse(p) for p in (path, *probes)}
    return _scan_tree(path, trees[path], members, _SourceIndex(list(trees.values())))


def _scan_tree(
    path: Path, tree: ast.Module, members: dict[str, int], index: _SourceIndex
) -> tuple[list[StaticCode], list[UnresolvedExpression]]:
    # A probe module outside the repo (the scanner's own tests) is reported by its full path.
    relative = (
        path.relative_to(REPO_ROOT).as_posix()
        if path.is_relative_to(REPO_ROOT)
        else path.as_posix()
    )

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
        if _resolve_expr(argument, enclosing, index, frozenset()) is None and _is_rerender(
            argument, enclosing, index
        ):
            continue

        status = _status_argument(node)
        if status is None:
            unresolved.append(
                UnresolvedExpression(
                    file=relative, line=argument.lineno, expression="status=<absent>"
                )
            )
            continue

        pairs = _resolve_pair(argument, status, enclosing, index, frozenset())
        if pairs is None:
            unresolved.append(
                UnresolvedExpression(
                    file=relative,
                    line=argument.lineno,
                    expression=f"{ast.unparse(argument)} / status={ast.unparse(status)}",
                )
            )
            continue
        for code, token in pairs:
            bucket = BY_CAUSE if token == BY_CAUSE else _bucket_of(token, members)
            if bucket is None:
                unresolved.append(
                    UnresolvedExpression(
                        file=relative, line=status.lineno, expression=f"status={token}"
                    )
                )
                continue
            codes.append(StaticCode(code=code, bucket=bucket))
    return codes, unresolved


_Operand = ast.expr | frozenset[str]
"""One side of a `(code, status)` pair while it is being resolved: still an expression in the
current function's context, or already a set of values carried down from a callee."""


def _is_forwarded(
    expr: _Operand, func: ast.FunctionDef | ast.AsyncFunctionDef | None, index: _SourceIndex
) -> str | None:
    """The parameter name `expr` forwards, when it is a bare parameter of `func` that nothing in
    `func` reassigns and no module constant of `func`'s own module shadows; otherwise `None`."""
    if not isinstance(expr, ast.Name) or func is None:
        return None
    name = expr.id
    if name not in _param_names(func) or name in index.module_constants(expr):
        return None
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return None
    return name


def _settle(
    expr: _Operand,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _SourceIndex,
    visited: frozenset[int],
    *,
    is_status: bool,
) -> frozenset[str] | None:
    """Resolve one operand in the current context. A status that will not fold is `BY_CAUSE`
    (`status_of(error)`, `self.status`, a name holding one): the number is chosen at runtime by
    whose frame raised. A code that will not fold is `None`, and the site is unresolved."""
    if isinstance(expr, frozenset):
        return expr
    resolved = _resolve_expr(expr, func, index, visited)
    if resolved is None:
        return frozenset({BY_CAUSE}) if is_status else None
    return frozenset(resolved)


def _resolve_pair(
    code: _Operand,
    status: _Operand,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    index: _SourceIndex,
    visited: frozenset[int],
) -> set[tuple[str, str]] | None:
    """Every `(code, status token)` pair one construction site can produce, resolved together.

    Resolving the two arguments separately and crossing them would be wrong at exactly the sites
    that need this pass: `_workspace_error` is called with a dozen codes under four statuses, and
    a cross product would file every one of those codes under every one of those statuses. So when
    either argument is a parameter forwarded into `func`, the resolver walks `func`'s call sites
    and resolves each caller's pair in the caller's own context, keeping the pairing that caller
    actually wrote. An argument that is not forwarded is settled in `func`'s context once and
    carried down as a fixed set.
    """
    code_param = _is_forwarded(code, func, index)
    status_param = _is_forwarded(status, func, index)
    if code_param is None:
        code = _settle(code, func, index, visited, is_status=False)
        if code is None:
            return None
    if status_param is None:
        status = _settle(status, func, index, visited, is_status=True)
        assert status is not None

    if code_param is None and status_param is None:
        assert isinstance(code, frozenset) and isinstance(status, frozenset)
        return {(c, s) for c in code for s in status}

    assert func is not None
    if id(func) in visited or len(visited) >= _MAX_RESOLUTION_DEPTH:
        return None  # a cycle or runaway chain: resolve nothing rather than loop or guess
    next_visited = visited | {id(func)}

    pairs: set[tuple[str, str]] = set()
    for call in index.calls_by_target.get(func.name, ()):
        caller = index.enclosing_function(call)
        caller_code = _operand_at_caller(call, func, code_param, code, index, next_visited)
        caller_status = _operand_at_caller(call, func, status_param, status, index, next_visited)
        if caller_code is None or caller_status is None:
            return None
        resolved = _resolve_pair(caller_code, caller_status, caller, index, next_visited)
        if resolved is None:
            return None
        pairs.update(resolved)
    return pairs or None


def _operand_at_caller(
    call: ast.Call,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    param: str | None,
    settled: _Operand,
    index: _SourceIndex,
    visited: frozenset[int],
) -> _Operand | None:
    """What one caller contributes for an operand: the argument it passed for the forwarded
    parameter, the parameter's default (settled in the callee's context) when it passed none, or
    the already-settled set when the operand was not forwarded at all."""
    if param is None:
        return settled
    argument = _argument_for_param(call, func, param)
    if argument is not None:
        return argument
    default = _param_default(func, param)
    if default is None:
        return None
    resolved = _resolve_expr(default, func, index, visited)
    return None if resolved is None else frozenset(resolved)


def _source_files() -> Iterator[Path]:
    yield from sorted(PACKAGE_ROOT.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def collect_static() -> StaticInventory:
    """Pass 1 -- AST walk with interprocedural constant folding over every module under
    `src/vqapr`, each resolved code bucketed by the `Status` it is raised under.

    Every module is parsed first and indexed together, so a code forwarded into a refusal helper
    resolves whether or not the helper's callers share its file.
    """
    members = status_members()
    trees = [(path, _parse(path)) for path in _source_files()]
    index = _SourceIndex([tree for _path, tree in trees])
    codes: set[StaticCode] = set()
    unresolved: list[UnresolvedExpression] = []
    for path, tree in trees:
        file_codes, file_unresolved = _scan_tree(path, tree, members, index)
        codes.update(file_codes)
        unresolved.extend(file_unresolved)
    unresolved.sort(key=lambda entry: (entry.file, entry.line))
    return StaticInventory(
        codes=tuple(sorted(codes, key=lambda entry: (entry.bucket, entry.code))),
        unresolved=tuple(unresolved),
    )


def static_by_bucket(inventory: StaticInventory) -> dict[str, list[str]]:
    """`{"400": [...], ..., "by_cause": [...]}`: the `static` section of the baseline."""
    buckets: dict[str, set[str]] = {}
    for entry in inventory.codes:
        buckets.setdefault(entry.bucket, set()).add(entry.code)
    return {bucket: sorted(codes) for bucket, codes in sorted(buckets.items())}


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
    from vqapr.data.datasets import DatasetRegistration, Grain, require_declared, validate
    from vqapr.data.sources import SourceSpec
    from vqapr.domain.errors import VqaprError

    codes: list[str] = []

    naive = _write_parquet(
        tmp_path / "naive.parquet",
        "SELECT TIMESTAMP '2024-03-05 03:00:00' AS available_at, 'A' AS instrument, "
        "100.0::DOUBLE AS close",
    )
    registration = DatasetRegistration.of(
        "price_daily",
        "s",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "missing_col": "does_not_exist"},
        field_types={"close": "DOUBLE", "missing_col": "DOUBLE"},
    )
    diagnosis, _, _measured = validate(registration, SourceSpec.of("s", naive))
    codes.extend(failure.code for failure in diagnosis.failures)

    dup = _write_parquet(
        tmp_path / "dup.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0::DOUBLE),
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 999.0::DOUBLE),
             (TIMESTAMPTZ '2024-03-06 03:00:00+09', NULL, 1.0::DOUBLE)
           ) AS t(available_at, instrument, close)""",
    )
    clean_registration = DatasetRegistration.of(
        "price_daily",
        "s",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    diagnosis, _, _measured = validate(clean_registration, SourceSpec.of("s", dup))
    codes.extend(failure.code for failure in diagnosis.failures)

    # `docs/issues/archive/088`: a declared type is compared with what the file evaluates to. A
    # DECIMAL column is refused whatever it is declared as (duckdb types a bare `100.0`
    # literal as DECIMAL(4,1)), and an INTEGER column declared DOUBLE is a mismatch.
    decimal_close = _write_parquet(
        tmp_path / "decimal.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, 'A' AS instrument, "
        "100.0 AS close",
    )
    diagnosis, _, _measured = validate(clean_registration, SourceSpec.of("s", decimal_close))
    codes.extend(failure.code for failure in diagnosis.failures)
    integer_close = _write_parquet(
        tmp_path / "integer.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, 'A' AS instrument, "
        "100 AS close",
    )
    diagnosis, _, _measured = validate(clean_registration, SourceSpec.of("s", integer_close))
    codes.extend(failure.code for failure in diagnosis.failures)

    # An entry written before `field_types` was declared decodes as quarantined, and a read
    # on it is refused by name until it is registered again with the types.
    try:
        require_declared(
            DatasetRegistration.undeclared(
                "price_daily",
                "s",
                instrument_field="instrument",
                available_at="available_at",
                key_fields=("available_at", "instrument"),
                fields={"close": "close"},
                field_types=None,
                grain=Grain.INSTRUMENT_INSTANT,
            )
        )
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    # `grain` is required since record `137`; without it `of` raises before `validate` runs and
    # the whole scenario -- including the two diagnoses above -- was being dropped silently by
    # `collect_runtime`'s per-scenario guard.
    mismatched = DatasetRegistration.of(
        "price_daily",
        "other-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="rows",
        key_fields=("instrument",),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    diagnosis, _, _measured = validate(mismatched, SourceSpec.of("s", dup))
    codes.extend(failure.code for failure in diagnosis.failures)

    try:
        from vqapr.data import scan

        scan.describe(SourceSpec.of("s", tmp_path / "does-not-exist.parquet"))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    return codes


def _runtime_execution_table(tmp_path: Path) -> list[str]:
    from vqapr.data.sources import SourceSpec
    from vqapr.exchange.conventions import FillConvention, FillSelector
    from vqapr.exchange.execution_table import (
        ExecutionTable,
        ExecutionTableSpec,
        validate_execution_table,
    )

    codes: list[str] = []

    def _registration(path: Path) -> ExecutionTable:
        return ExecutionTable.of(
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
    diagnosis = validate_execution_table(_registration(bad_types))
    codes.extend(failure.code for failure in diagnosis.failures)

    dup_null = _write_parquet(
        tmp_path / "dup-null.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0::DOUBLE, 100.0::DOUBLE),
             (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 99.0::DOUBLE, 100.0::DOUBLE),
             (TIMESTAMPTZ '2024-03-06 15:30:00+09', NULL, true, 1.0::DOUBLE, 1.0::DOUBLE)
           ) AS t(trade_at, instrument, is_tradable, open, close)""",
    )
    diagnosis = validate_execution_table(_registration(dup_null))
    codes.extend(failure.code for failure in diagnosis.failures)

    bad_price = _write_parquet(
        tmp_path / "bad-price.parquet",
        """SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at, 'A' AS instrument,
                  true AS is_tradable, 99.0::DOUBLE AS open, 0.0::DOUBLE AS close""",
    )
    diagnosis = validate_execution_table(_registration(bad_price))
    codes.extend(failure.code for failure in diagnosis.failures)

    return codes


def _runtime_conformance_and_loading(tmp_path: Path) -> list[str]:
    from vqapr.domain.errors import VqaprError
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.public import register_constraint
    from vqapr.extension.conformance import conformance

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

            def project(self, call):
                return ConstraintBounds(lower_weights={}, upper_weights={})

            def monitor(self, call, account, bounds):
                return None
        """
    )
    # Wrong ARITY, not a wrong name. Renaming the member makes the class abstract, so
    # instantiation fails and `component.load.construction_failed` fires before the signature
    # check this fixture exists to provoke ever runs -- the exact silent-weakening this file's
    # own comment below warns about.
    stale = good.replace(
        "def monitor(self, call, account, bounds):", "def monitor(self, account, marks):"
    )
    missing = good.replace("def project(self, call):", "def unused(self):")
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
    from vqapr.project.registration import apply
    from vqapr.domain.errors import VqaprError

    # A run is the declaration that carries the sessions and the wall time since record `148`
    # (`agendas:` is no longer a section), so the two malformed-document scenarios that used to
    # be agendas are runs: one missing what a run must declare, one with the wrong shape for it.
    run = {
        "strategies": {"alpha": {}},
        "instruments": ["A"],
        "start": "2024-03-05T00:00:00+09:00",
        "end": "2024-03-06T00:00:00+09:00",
        "timezone": "Asia/Seoul",
        "exchange": "venue",
        "execution": {
            "dataset": "fills",
            "fill": {"at": "15:30", "timezone": "Asia/Seoul", "trade_price": "close"},
        },
        "initial_account": {"cash": "1000", "mode": "long_only", "positions": {}},
    }
    scenarios: list[dict] = [
        {"datasets": {"prices": {"source_id": "s", "path": "p.parquet"}}},
        {"runs": {"alpha": {**run, "sessions": ["2024-03-05"]}}},
        {"components": {"c": {"kind": "model", "path": "p.py", "object_name": "X"}}},
        {"runs": {"alpha": {**run, "at": "15:30", "sessions": "nope"}}},
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
    from vqapr.project.store import Workspace

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
        "'A' AS instrument, 1.0::DOUBLE AS close",
    )
    registration = _with_span(
        DatasetRegistration.of(
            "prices",
            "s",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        )
    )
    with Workspace.transaction(workspace) as t:
        t.register_dataset(registration, SourceSpec.of("s", prices))

    other = _write_parquet(
        tmp_path / "other.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, "
        "'B' AS instrument, 2.0::DOUBLE AS close",
    )
    conflicting = _with_span(
        DatasetRegistration.of(
            "prices",
            "s",
            instrument_field="instrument",
            available_at="available_at",
            grain="rows",
            key_fields=("instrument",),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        )
    )
    try:
        with Workspace.transaction(workspace) as t:
            t.register_dataset(conflicting, SourceSpec.of("s", prices))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    try:
        with Workspace.transaction(workspace) as t:
            t.register_dataset(registration, SourceSpec.of("s", other))
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)

    # A run that takes its sessions from a dataset nobody registered (record `148`: the run
    # declares its sessions; the workspace refuses an id it cannot resolve at registration).
    from datetime import time

    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.project.run import RunDefinition, StrategyEntry

    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        "from vqapr.public import StrategyModel, Hold\n\n"
        "class Strategy(StrategyModel):\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='inventory')\n",
        encoding="utf-8",
    )
    with Workspace.transaction(workspace) as t:
        t.register_component(
            ComponentRef.of(
                "strategy",
                ComponentKind.STRATEGY_MODEL,
                strategy,
                "Strategy",
                fingerprint=fingerprint_component(
                    strategy, kind=ComponentKind.STRATEGY_MODEL, object_name="Strategy"
                ),
            )
        )
    try:
        with Workspace.transaction(workspace) as t:
            t.register_run(
                RunDefinition(
                    run_id="unsourced",
                    strategy=StrategyEntry("strategy"),
                    instruments=("A",),
                    timezone="Asia/Seoul",
                    at=time(15, 30),
                    sessions_from="does-not-exist",
                )
            )
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
    from vqapr.project.store import Workspace

    workspace = Workspace.create(tmp_path)
    prices = _write_parquet(
        tmp_path / "prices.parquet",
        "SELECT TIMESTAMPTZ '2024-03-05 03:00:00+09' AS available_at, "
        "'A' AS instrument, 1.0::DOUBLE AS close",
    )
    with Workspace.transaction(workspace) as t:
        t.register_dataset(
            _with_span(
                DatasetRegistration.of(
                    "prices",
                    "s",
                    instrument_field="instrument",
                    available_at="available_at",
                    grain="instrument_instant",
                    key_fields=("available_at", "instrument"),
                    fields={"close": "close"},
                    field_types={"close": "DOUBLE"},
                )
            ),
            SourceSpec.of("s", prices),
        )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 12, tzinfo=UTC),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(),
        consumer_id="test-consumer",
    )
    undeclared = DataRequirement.of("prices", "close", lookback=RowsLookback(1))
    codes: list[str] = []
    try:
        window.observations(undeclared)
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)
    return codes


def _runtime_datamodel_output(tmp_path: Path) -> list[str]:
    """A datamodel's first non-empty session states the output's field types.

    `docs/issues/archive/088`: a value field pyarrow types as decimal is one no dataset can declare, so
    the output refuses it at the first append rather than after every session has run. The
    layer is stood in for by the two attributes the output reads from it -- constructing a
    `FrozenDataModel` needs a fingerprinted component and a frozen agenda, none of which
    bears on the refusal.
    """
    from datetime import UTC, datetime
    from decimal import Decimal
    from types import SimpleNamespace

    from vqapr.domain.errors import VqaprError
    from vqapr.flow.datamodel.output import DataModelOutput

    codes: list[str] = []
    output = DataModelOutput(
        tmp_path, SimpleNamespace(dataset_id="scores", value_fields=("score",))
    )
    output.open()
    try:
        output.append(
            [
                {
                    "available_at": datetime(2024, 3, 5, 12, tzinfo=UTC),
                    "instrument": "A",
                    "score": Decimal("1.5"),
                }
            ]
        )
    except VqaprError as error:
        codes.extend(failure.code for failure in error.failures)
    return codes


_RUNTIME_SCENARIOS = (
    _runtime_dataset_schema_and_key,
    _runtime_execution_table,
    _runtime_conformance_and_loading,
    _runtime_declaration_read,
    _runtime_workspace,
    _runtime_model_window,
    _runtime_datamodel_output,
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
    """Assemble the full deterministic baseline document.

    `static` is keyed by bucket -- a `Status` number as a string, or `by_cause` -- and holds the
    sorted codes raised under it. No file and no line: a code that moves between files or slides
    within one is not a change to the refusal vocabulary, and this baseline measures nothing else.
    """
    static = collect_static()
    runtime_codes = collect_runtime()
    static_code_set = {entry.code for entry in static.codes}
    coverage_gap = sorted(static_code_set - set(runtime_codes))
    return {
        "schema": SCHEMA,
        "static": static_by_bucket(static),
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
