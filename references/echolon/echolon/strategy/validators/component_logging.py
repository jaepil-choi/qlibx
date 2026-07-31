"""AST validator for the ``log_<component>_output`` convention.

For each component file, checks that the required method's body:

- Calls ``self.log_<component>_output(<arg>)`` at least once. Missing →
  VAL-003. The argument is the output the downstream analyzer will
  consume; failing to log it means post-run tooling sees nothing.

- Passes a matching BaseModel (``EntrySignalOutput`` etc.), not a dict
  literal and not a different schema type. Wrong type → VAL-006.

Also flags, anywhere in the file:

- ``self.params.get(...)`` — the defensive dict-access antipattern
  (framework contract: every declared param is on ``self`` as an
  attribute; ``.get()`` with a default masks missing-param bugs).
  Surfaces as PRM-004.

Silently skips absent files (preflight STR-001 territory).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Tuple, List, Optional

from echolon.strategy.validators import Finding, Report


# Maps file name → (class_name, method_name, log_call_name, expected_schema_identifier)
_CONTRACT: Dict[str, Tuple[str, str, str, str]] = {
    "entry.py": ("entry_rule",     "generate_signal", "log_entry_output", "EntrySignalOutput"),
    "exit.py":  ("exit_rule",      "should_exit",     "log_exit_output",  "ExitSignalOutput"),
    "risk.py":  ("risk_manager",   "can_trade",       "log_risk_output",  "RiskOutput"),
    "sizer.py": ("position_sizer", "calculate_size",  "log_sizer_output", "SizerOutput"),
}


def _is_self_attr_call(node: ast.Call, attr_name: str) -> bool:
    """True if ``node`` is a call of the form ``self.<attr_name>(...)``."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == attr_name
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    )


def _resolve_name_binding(
    method_body: List[ast.stmt], target_name: str,
) -> Optional[ast.AST]:
    """Scan the method body for ``<target_name> = <rhs>`` assignments and
    return the RHS of the first match. Used to trace a log call's local-
    variable argument back to its instantiation site."""
    for stmt in method_body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == target_name:
                    return stmt.value
    return None


def _call_function_tail(call: ast.Call) -> Optional[str]:
    """Return the trailing identifier of a call's function expression."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _resolve_arg_type_identifier(
    arg: ast.AST, method_body: List[ast.stmt],
) -> str:
    """Best-effort identification of the type passed as the log-call arg.

    Returns a string describing what was passed:
    - ``"<SchemaName>"`` — looks like a BaseModel instantiation (we
      matched ``XxxOutput(...)`` either inline or via a local variable).
    - ``"dict"`` — dict literal.
    - ``"unknown"`` — couldn't resolve. Do NOT raise VAL-006 on this —
      the agent may be using an approach we don't recognize (FP insurance).
    """
    if isinstance(arg, ast.Dict):
        return "dict"

    # Inline call: self.log_entry_output(EntrySignalOutput(...))
    if isinstance(arg, ast.Call):
        tail = _call_function_tail(arg)
        if tail:
            return tail

    # Local variable: self.log_entry_output(out), where ``out = EntrySignalOutput(...)``.
    if isinstance(arg, ast.Name):
        rhs = _resolve_name_binding(method_body, arg.id)
        if rhs is None:
            return "unknown"
        if isinstance(rhs, ast.Dict):
            return "dict"
        if isinstance(rhs, ast.Call):
            tail = _call_function_tail(rhs)
            if tail:
                return tail

    return "unknown"


def _find_method_in_class(
    tree: ast.Module, class_name: str, method_name: str,
) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == method_name:
                    return m
    return None


def _check_log_call(
    method: ast.FunctionDef,
    log_call_name: str,
    expected_schema: str,
    file_path: Path,
    class_name: str,
    method_name: str,
    report: Report,
) -> None:
    found_log_calls: List[ast.Call] = []
    for node in ast.walk(method):
        if isinstance(node, ast.Call) and _is_self_attr_call(node, log_call_name):
            found_log_calls.append(node)

    if not found_log_calls:
        report.add(Finding(
            code="VAL-003",
            message=(
                f"{class_name}.{method_name} never calls self.{log_call_name}() — "
                f"downstream analyzers will see no log record."
            ),
            context={
                "file": str(file_path),
                "component": class_name,
                "method": method_name,
                "missing_call": log_call_name,
                "expected_schema": expected_schema,
            },
        ))
        return

    # Check argument type on the log calls found. Multiple calls are
    # legal; we only need one to be correct.
    for call in found_log_calls:
        if not call.args:
            continue
        arg = call.args[0]
        arg_type = _resolve_arg_type_identifier(arg, method.body)
        if arg_type == expected_schema:
            return  # found a good call; don't surface a finding
        if arg_type == "unknown":
            continue  # can't determine type — FP insurance, skip
        # Definite mismatch: dict or wrong schema name
        report.add(Finding(
            code="VAL-006",
            message=(
                f"self.{log_call_name} argument is {arg_type!r}, "
                f"expected {expected_schema!r}"
            ),
            context={
                "file": str(file_path),
                "component": class_name,
                "method": method_name,
                "expected_return": expected_schema,
                "actual_annotation": arg_type,
            },
        ))
        return


def _check_params_dict_get(tree: ast.Module, file_path: Path, report: Report) -> None:
    """Flag any ``self.params.get(...)`` call anywhere in the module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        # Must be on an Attribute whose .value is Attribute("params") on Name("self")
        outer = func.value
        if (
            isinstance(outer, ast.Attribute)
            and outer.attr == "params"
            and isinstance(outer.value, ast.Name)
            and outer.value.id == "self"
        ):
            # Format the call as best we can for the context dict.
            call_repr = "self.params.get(...)"
            if node.args and isinstance(node.args[0], ast.Constant):
                call_repr = f"self.params.get({node.args[0].value!r})"
            report.add(Finding(
                code="PRM-004",
                message=f"Defensive self.params.get() in {file_path.name}",
                context={
                    "file": str(file_path),
                    "line": node.lineno,
                    "call": call_repr,
                },
            ))


def validate_component_logging(strategy_dir: "Path | str") -> Report:
    """Return a Report with logging-convention findings for each of the
    4 required component files in ``strategy_dir``."""
    strategy_dir = Path(strategy_dir)
    report = Report()

    for file_name, (class_name, method_name, log_call, expected_schema) in _CONTRACT.items():
        file_path = strategy_dir / file_name
        if not file_path.exists():
            continue

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # upstream concern

        method = _find_method_in_class(tree, class_name, method_name)
        if method is None:
            continue  # STR-003 territory (component_signatures handles this)

        _check_log_call(
            method, log_call, expected_schema, file_path, class_name, method_name, report,
        )
        _check_params_dict_get(tree, file_path, report)

    return report
