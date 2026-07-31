"""Validate that component modules import, their classes expose the right
method signatures, and ``strategy_params.DEFAULT_PARAMS`` has the 4
required top-level component keys.

Unlike ``component_signatures`` which AST-walks without executing user
code, this validator IMPORTS each module via ``StrategyLoader`` and
uses ``inspect.signature()`` on the bound method. That's the only way to
detect actual signature mismatches — AST sees the source, but doesn't
verify that the imported module loads cleanly or that `self` binding
produces the expected bound-method shape.

Error codes:
- STR-002: module fails to import (echolon loads by file path; an import
  error here = guaranteed runtime failure).
- PRM-002: DEFAULT_PARAMS missing a required top-level key, or the
  value isn't a dict.
- VAL-005: method signature has wrong arity (number of required positional
  args after ``self``). Argument names are the author's choice — the
  framework calls these methods positionally (principle 5: structural over
  lexical). A sizer with ``def calculate_size(self, signal_data)`` is
  just as valid as ``def calculate_size(self, entry_signal)``.

Silently skips absent files (preflight STR-001 territory).
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Dict, Tuple

from echolon.strategy.validators import Finding, Report


# Each entry: (class_name, method_name, required_positional_arity_after_self).
# Only arity matters — the framework calls these positionally, so
# argument names are the author's choice (principle 5: structural over
# lexical). A sizer with ``def calculate_size(self, signal_data)`` is
# just as valid as ``def calculate_size(self, entry_signal)``.
_COMPONENT_CONTRACT: Dict[str, Tuple[str, str, int]] = {
    "entry": ("entry_rule",     "generate_signal", 0),
    "exit":  ("exit_rule",      "should_exit",     0),
    "risk":  ("risk_manager",   "can_trade",       0),
    "sizer": ("position_sizer", "calculate_size",  1),
}

_REQUIRED_PARAM_KEYS = ("entry_params", "exit_params", "risk_params", "sizer_params")


def _check_component(
    strategy_dir: Path,
    module_stem: str,
    class_name: str,
    method_name: str,
    expected_arity: int,
    report: Report,
) -> None:
    from echolon.strategy.loader import StrategyLoader

    file_path = strategy_dir / f"{module_stem}.py"
    if not file_path.exists():
        return  # preflight STR-001 territory

    loader = StrategyLoader(strategy_dir)
    try:
        module = loader.load_module(module_stem)
    except Exception as e:  # noqa: BLE001 — any import error is STR-002
        report.add(Finding(
            code="STR-002",
            message=f"Cannot import {module_stem}.py: {type(e).__name__}: {e}",
            context={
                "file": str(file_path),
                "expected_class": class_name,
                "exception_type": type(e).__name__,
                "exception_repr": repr(e),
            },
        ))
        return

    cls = getattr(module, class_name, None)
    if cls is None:
        # preflight STR-002 (class export) territory — silent here.
        return

    method = getattr(cls, method_name, None)
    if method is None:
        # preflight / component_signatures STR-003 territory — silent here.
        return

    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return  # built-in or otherwise unreadable; skip

    # Drop ``self`` then check arity of required positional params.
    params = list(sig.parameters.values())
    if params and params[0].name == "self":
        params = params[1:]
    required_positional = [
        p for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        )
        and p.default is inspect.Parameter.empty
    ]
    actual_arity = len(required_positional)
    if actual_arity != expected_arity:
        actual_names = [p.name for p in required_positional]
        report.add(Finding(
            code="VAL-005",
            message=(
                f"{class_name}.{method_name} arity mismatch: "
                f"got {actual_arity} required positional args {actual_names}, "
                f"expected {expected_arity}"
            ),
            context={
                "file": str(file_path),
                "component": class_name,
                "method": method_name,
                "expected": f"{method_name}(self, + {expected_arity} required positional arg(s))",
                "actual": f"{method_name}(self, {', '.join(actual_names)})",
            },
        ))


def _check_default_params(strategy_dir: Path, report: Report) -> None:
    from echolon.strategy.loader import StrategyLoader

    file_path = strategy_dir / "strategy_params.py"
    if not file_path.exists():
        return  # preflight STR-001 territory

    loader = StrategyLoader(strategy_dir)
    try:
        module = loader.load_module("strategy_params")
    except Exception as e:  # noqa: BLE001
        report.add(Finding(
            code="STR-002",
            message=f"Cannot import strategy_params.py: {type(e).__name__}: {e}",
            context={
                "file": str(file_path),
                "expected_class": "DEFAULT_PARAMS",
                "exception_type": type(e).__name__,
                "exception_repr": repr(e),
            },
        ))
        return

    default_params = getattr(module, "DEFAULT_PARAMS", None)
    if default_params is None or not isinstance(default_params, dict):
        report.add(Finding(
            code="PRM-002",
            message="strategy_params.py does not expose DEFAULT_PARAMS as a dict",
            context={
                "file": str(file_path),
                "missing_keys": list(_REQUIRED_PARAM_KEYS),
                "present_keys": [],
            },
        ))
        return

    missing_keys = [k for k in _REQUIRED_PARAM_KEYS if k not in default_params]
    if missing_keys:
        report.add(Finding(
            code="PRM-002",
            message=f"DEFAULT_PARAMS missing required top-level keys: {missing_keys}",
            context={
                "file": str(file_path),
                "missing_keys": missing_keys,
                "present_keys": sorted(default_params.keys()),
            },
        ))

    non_dict_keys = [
        k for k in _REQUIRED_PARAM_KEYS
        if k in default_params and not isinstance(default_params[k], dict)
    ]
    if non_dict_keys:
        report.add(Finding(
            code="PRM-002",
            message=f"DEFAULT_PARAMS keys are not dicts: {non_dict_keys}",
            context={
                "file": str(file_path),
                "non_dict_keys": non_dict_keys,
                "expected_type": "dict",
            },
        ))


def validate_component_integration(strategy_dir: "Path | str") -> Report:
    """Return a Report with component-import / signature / DEFAULT_PARAMS
    findings for the strategy at ``strategy_dir``."""
    strategy_dir = Path(strategy_dir)
    report = Report()

    for module_stem, (class_name, method_name, expected_arity) in _COMPONENT_CONTRACT.items():
        _check_component(
            strategy_dir, module_stem, class_name, method_name, expected_arity, report,
        )

    _check_default_params(strategy_dir, report)

    return report
