"""AST-based validator for parameter-access discipline.

Flags numeric literals in condition-RHS positions (PRM-003) that suggest
a hardcoded trading threshold, and any ``self.params.get(...)`` call
(PRM-004). Everything else — loop counters, None comparisons, index
slicing, kwargs, default args, small integers in arithmetic, string
literals — is allowlisted.

The positive rule:
  ``if <identifier-like> <compop> <numeric literal>`` in a Compare node
  where the literal is NOT:
    - inside a ``range()`` call
    - inside a Subscript / slice
    - a keyword-argument value
    - a default argument in a FunctionDef
    - part of a numeric ``is``/``is not`` against None
    - one of the "small int" constants {-1, 0, 1}
  surfaces as PRM-003.

String literals on the RHS of comparisons receive a blanket allowance —
regime strings, signal enums, and other framework-defined string constants
are not trading thresholds.

Ships in warning-only posture: callers decide whether PRM-003 findings
block the pipeline. The default is surface-but-don't-block until the
canary test (B1-8) has cleared the validator against real baselines.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

from echolon.strategy.validators import Finding, Report


_COMPONENT_FILES = ("entry.py", "exit.py", "risk.py", "sizer.py")

# Structural "sentinel" constants: -1/0/1 integer-or-float values that are
# never trading thresholds (index arithmetic, loop counters, minimum-lot
# gates). Do not flag as PRM-003.
_STRUCTURAL_CONSTANT_ALLOWLIST: Set = {-1, 0, 1, -1.0, 0.0, 1.0}


def _load_declared_param_keys(strategy_dir: Path) -> "set[str] | None":
    """Union of all DEFAULT_PARAMS section keys, loaded at RUNTIME.

    DEFAULT_PARAMS is composed by ``framework.compose_default_strategy()`` plus
    cross-section copies (e.g. ``DEFAULT_PARAMS['sizer_params']['atr_period'] =
    DEFAULT_PARAMS['exit_params']['atr_period']``), so it cannot be parsed
    statically — we execute strategy_params.py via the same StrategyLoader the
    backtest/smoke use. Returns ``None`` if it can't be loaded, so the PRM-006
    check no-ops (no false positive, no crash) — that's PRM-002 territory.
    """
    try:
        from echolon.strategy.loader import StrategyLoader

        sp = StrategyLoader(strategy_dir).load_module("strategy_params")
        default_params = getattr(sp, "DEFAULT_PARAMS", None)
        if not isinstance(default_params, dict):
            return None
        keys: Set = set()
        for section in default_params.values():
            if isinstance(section, dict):
                keys.update(str(k) for k in section.keys())
        return keys
    except Exception:  # noqa: BLE001 — PRM-002 territory; skip the completeness check
        return None


class _ParameterAccessVisitor(ast.NodeVisitor):
    """Walks a single component file, accumulating findings.

    Uses a ``_allowlist_depth`` counter to track whether we're inside an
    allowlisted position (Subscript, Call, FunctionDef default). Numeric
    literals seen inside those contexts are silently ignored.
    """

    def __init__(self, file_path: Path, report: Report, declared_params=None) -> None:
        self.file_path = file_path
        self.report = report
        # Union of DEFAULT_PARAMS keys (or None → skip the PRM-006 check).
        self.declared_params = declared_params
        # Counter > 0 means we're inside a position where numeric literals
        # are not threshold-like (range args, subscripts, call args, defaults).
        self._allowlist_depth = 0

    # ----- helpers ---------------------------------------------------------

    def _descend_allowlisted(self, node: ast.AST) -> None:
        self._allowlist_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._allowlist_depth -= 1

    # ----- allowlist contexts ---------------------------------------------

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # PRM-006: self.params['<missing>'] is a guaranteed bar-time KeyError.
        self._check_self_params_subscript(node)
        # Both the value (expression being subscripted) and the slice are
        # structural access — any numeric literal inside is allowed.
        self._descend_allowlisted(node)

    def _check_self_params_subscript(self, node: ast.Subscript) -> None:
        """Flag ``self.params['<const>']`` whose key is absent from
        DEFAULT_PARAMS (PRM-006). No-op when the declared set is unavailable
        (``declared_params is None``) or the key is not a string constant (can't
        resolve statically — never false-positive)."""
        if self.declared_params is None:
            return
        value = node.value
        if not (
            isinstance(value, ast.Attribute)
            and value.attr == "params"
            and isinstance(value.value, ast.Name)
            and value.value.id == "self"
        ):
            return
        key_node = node.slice
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            return
        key = key_node.value
        if key not in self.declared_params:
            self.report.add(Finding(
                code="PRM-006",
                message=(
                    f"Parameter {key!r} is read via self.params[{key!r}] in "
                    f"{self.file_path.name} but is absent from DEFAULT_PARAMS — "
                    f"a KeyError at bar-time. Declare it in strategy_params.py."
                ),
                context={
                    "file": str(self.file_path),
                    "line": node.lineno,
                    "param": key,
                },
            ))

    def visit_keyword(self, node: ast.keyword) -> None:
        # keyword-argument value: allowed.
        self._descend_allowlisted(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Default-argument values land in node.args.defaults — walk them
        # allowlisted. Body walks with normal rules.
        for default in list(node.args.defaults) + list(node.args.kw_defaults or []):
            if default is None:
                continue
            self._allowlist_depth += 1
            try:
                self.visit(default)
            finally:
                self._allowlist_depth -= 1
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        # range(...) — any numeric args inside are iteration counters.
        if isinstance(node.func, ast.Name) and node.func.id == "range":
            self._descend_allowlisted(node)
            return

        # self.params.get(...) — flag as PRM-004, then recurse allowlisted.
        if self._is_self_params_get(node):
            call_repr = "self.params.get(...)"
            if node.args and isinstance(node.args[0], ast.Constant):
                call_repr = f"self.params.get({node.args[0].value!r})"
            self.report.add(Finding(
                code="PRM-004",
                message=f"Defensive self.params.get() in {self.file_path.name}",
                context={
                    "file": str(self.file_path),
                    "line": node.lineno,
                    "call": call_repr,
                },
            ))

        # Generic call: walk the entire call allowlisted. Positional numeric
        # literals in function calls are nearly always library-level (timeouts,
        # buffer sizes, retry counts), not strategy thresholds.
        self._descend_allowlisted(node)

    @staticmethod
    def _is_self_params_get(node: ast.Call) -> bool:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            return False
        outer = func.value
        return (
            isinstance(outer, ast.Attribute)
            and outer.attr == "params"
            and isinstance(outer.value, ast.Name)
            and outer.value.id == "self"
        )

    # ----- the positive rule ----------------------------------------------

    def visit_Compare(self, node: ast.Compare) -> None:
        """Detect ``<identifier-like> <cmp> <numeric_literal>`` threshold smells.

        A Compare node has a left-most expression and N pairwise comparators.
        We evaluate each pair and surface PRM-003 when the RHS is a numeric
        constant in a suspicious context. The sub-nodes are visited with
        normal rules afterwards (generic_visit).
        """
        if self._allowlist_depth == 0:
            # Build all pairwise (lhs, op, rhs) from the chained comparison.
            prev = node.left
            for op, comp in zip(node.ops, node.comparators):
                self._maybe_flag(prev, op, comp, node.lineno)
                prev = comp

        self.generic_visit(node)

    def _maybe_flag(
        self,
        lhs: ast.AST,
        op: ast.cmpop,
        rhs: ast.AST,
        lineno: int,
    ) -> None:
        # None comparisons: `x is None`, `x is not None` — always allowed.
        if isinstance(op, (ast.Is, ast.IsNot)):
            return

        # LHS must look like a computed value (variable, attribute access,
        # subscript, or call result) — i.e., something that holds an indicator
        # reading or derived value.
        if not isinstance(lhs, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
            return

        # RHS must be a bare constant.
        if not isinstance(rhs, ast.Constant):
            return

        val = rhs.value

        # Booleans: True/False comparisons — allowed.
        if isinstance(val, bool):
            return

        # None on the RHS: `x == None` (less idiomatic but allowed).
        if val is None:
            return

        # String literals: regime names, signal enums — blanket allowance.
        if isinstance(val, str):
            return

        # Must be numeric at this point.
        if not isinstance(val, (int, float)):
            return

        # Structural constants are not thresholds.
        if val in _STRUCTURAL_CONSTANT_ALLOWLIST:
            return

        literal_repr = repr(val)
        self.report.add(Finding(
            code="PRM-003",
            message=(
                f"Hardcoded threshold literal {literal_repr} in comparison — "
                f"move to strategy_params and reference via self.<param>"
            ),
            context={
                "file": str(self.file_path),
                "line": lineno,
                "literal": literal_repr,
                "suggestion": "declare as self.<param_name>, set in strategy_params.py",
                "severity": "warning",
            },
        ))


def validate_parameter_access(strategy_dir: "Path | str") -> Report:
    """Return a Report flagging hardcoded threshold literals (PRM-003),
    ``self.params.get()`` calls (PRM-004), and ``self.params['X']`` reads of a
    key absent from DEFAULT_PARAMS (PRM-006) across the 4 component files in
    ``strategy_dir``.

    PRM-003 findings carry ``context["severity"] = "warning"`` — callers
    decide whether to treat them as blocking. The default posture is
    surface-but-don't-block until canary baseline (B1-8) has run.

    PRM-004 has no severity flag; it is always a bug per framework
    contract (parameters must be accessed via ``self.<attr>``).

    PRM-006 is a hard finding: a missing param is a guaranteed bar-time
    KeyError. The declared key set is loaded once (runtime) via StrategyLoader
    because DEFAULT_PARAMS is composed dynamically; if it can't be loaded the
    PRM-006 check is skipped (no false positive).

    Silently skips component files that don't exist — file-presence is
    preflight's responsibility (STR-001), not ours.
    """
    strategy_dir = Path(strategy_dir)
    report = Report()

    # Loaded once for the whole strategy (union of all sections). None → the
    # PRM-006 completeness check is skipped (e.g. malformed strategy_params).
    declared_params = _load_declared_param_keys(strategy_dir)

    for file_name in _COMPONENT_FILES:
        file_path = strategy_dir / file_name
        if not file_path.exists():
            continue
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visitor = _ParameterAccessVisitor(file_path, report, declared_params)
        visitor.visit(tree)

    return report
