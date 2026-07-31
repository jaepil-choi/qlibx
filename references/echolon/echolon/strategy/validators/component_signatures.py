"""Validate component-file method signatures against the echolon protocol.

AST-based — doesn't import the modules (keeps the validator fast and
avoids running user code at validation time). For each of the 4 required
component files, checks:

- STR-003: the class defines the required method.
- VAL-006: IF the method declares a return annotation, that annotation's
  trailing identifier matches the expected BaseModel name.

Intentionally NOT checked (would violate principle 2 — policy vs
correctness):
- Return annotation presence. Missing annotation is a stylistic choice.
- Method argument types. The framework doesn't enforce these.
- Component file presence (that's preflight's STR-001 job).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Tuple

from echolon.strategy.validators import Finding, Report


# (class_name, method_name, expected_return_type_tail_identifier)
_CONTRACT: Dict[str, Tuple[str, str, str]] = {
    "entry.py": ("entry_rule",     "generate_signal", "EntrySignalOutput"),
    "exit.py":  ("exit_rule",      "should_exit",     "ExitSignalOutput"),
    "risk.py":  ("risk_manager",   "can_trade",       "RiskOutput"),
    "sizer.py": ("position_sizer", "calculate_size",  "SizerOutput"),
}


def _annotation_tail(annotation: ast.AST | None) -> str | None:
    """Return the trailing identifier of an annotation AST node.

    Handles:
    - ``ast.Name`` (bare: EntrySignalOutput) -> "EntrySignalOutput"
    - ``ast.Constant`` (string forward ref: "EntrySignalOutput") -> "EntrySignalOutput"
    - ``ast.Attribute`` (dotted: schemas.EntrySignalOutput) -> "EntrySignalOutput"
    - ``None`` (no annotation) -> None

    Anything else (generics, unions, subscripts) returns the raw AST dump
    so callers can surface the unusual shape verbatim in context.
    """
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        # String forward reference — take the trailing identifier.
        return annotation.value.strip().split(".")[-1]
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return ast.dump(annotation)


def _find_class_in_module(tree: ast.Module, class_name: str) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _find_method_in_class(
    class_node: ast.ClassDef, method_name: str
) -> ast.FunctionDef | None:
    for node in class_node.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == method_name
        ):
            return node
    return None


def validate_component_signatures(strategy_dir: "Path | str") -> Report:
    """Return a Report with findings for method / return-annotation issues
    across the 4 required component files in ``strategy_dir``.

    Silently skips files that don't exist — that's preflight's STR-001
    concern, not ours.
    """
    strategy_dir = Path(strategy_dir)
    report = Report()

    for file_name, (class_name, method_name, expected_return) in _CONTRACT.items():
        file_path = strategy_dir / file_name
        if not file_path.exists():
            continue  # file-presence is preflight's concern (STR-001)

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            # Syntax errors propagate upstream — surface as STR-003 so
            # the caller still gets a structured finding.
            report.add(Finding(
                code="STR-003",
                message=f"Cannot parse {file_name}: {e}",
                context={
                    "file": str(file_path),
                    "component": class_name,
                    "method": method_name,
                },
            ))
            continue

        class_node = _find_class_in_module(tree, class_name)
        if class_node is None:
            # preflight STR-002 already catches wrong class names; skip.
            continue

        method_node = _find_method_in_class(class_node, method_name)
        if method_node is None:
            report.add(Finding(
                code="STR-003",
                message=(
                    f"Class {class_name} in {file_name} is missing required method "
                    f"{method_name}"
                ),
                context={
                    "file": str(file_path),
                    "component": class_name,
                    "class_name": class_name,
                    "method": method_name,
                    "missing_method": method_name,
                },
            ))
            continue

        actual_annotation_tail = _annotation_tail(method_node.returns)
        if actual_annotation_tail is None:
            # Missing annotation → NO finding (FP-insurance principle 2).
            continue
        if actual_annotation_tail != expected_return:
            report.add(Finding(
                code="VAL-006",
                message=(
                    f"{class_name}.{method_name} return annotation is "
                    f"{actual_annotation_tail!r}, expected {expected_return!r}"
                ),
                context={
                    "file": str(file_path),
                    "component": class_name,
                    "method": method_name,
                    "expected_return": expected_return,
                    "actual_annotation": actual_annotation_tail,
                },
            ))

    return report
