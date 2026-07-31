"""Pre-load strategy validation.

Runs all cheap, file-level checks against a strategy directory BEFORE the
backtest or live engine tries to instantiate the strategy. Each check raises
the appropriate catalog code on failure so LLM callers get the most specific,
actionable error possible.

Order of checks (fail fast on the cheapest check):
    1. STR-001: all 6 required files present
    2. STR-002: each <component>.py exports the expected class name
    3. PRM-002: strategy_params.DEFAULT_PARAMS has all 4 component keys
    4. PRM-001: every component sub-dict contains 'printlog'

STR-003 (method not implemented) is runtime-only; preflight cannot check it
at the file level.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from echolon.errors import raise_error

REQUIRED_FILES = [
    "entry.py",
    "exit.py",
    "risk.py",
    "sizer.py",
    "strategy_params.py",
    "strategy_indicator_list.json",
]

# Map file name -> expected class name exported by that file.
EXPECTED_CLASSES = {
    "entry.py": "entry_rule",
    "exit.py":  "exit_rule",
    "risk.py":  "risk_manager",
    "sizer.py": "position_sizer",
}

REQUIRED_PARAM_KEYS = ("entry_params", "exit_params", "risk_params", "sizer_params")


def _check_required_files(strategy_dir: Path) -> None:
    missing = [f for f in REQUIRED_FILES if not (strategy_dir / f).exists()]
    if missing:
        raise_error(
            "STR-001",
            strategy_dir=str(strategy_dir),
            missing_files=", ".join(missing),
        )


def _check_required_classes(strategy_dir: Path) -> None:
    for file_name, expected_class in EXPECTED_CLASSES.items():
        file_path = strategy_dir / file_name
        spec = importlib.util.spec_from_file_location(
            f"_preflight_{file_path.stem}_{id(file_path)}",
            file_path,
        )
        if spec is None or spec.loader is None:
            raise_error(
                "STR-002",
                file=str(file_path),
                expected_class=expected_class,
                found_classes="<spec failed>",
            )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise_error(
                "STR-002",
                file=str(file_path),
                expected_class=expected_class,
                found_classes=f"<module failed to import: {exc}>",
            )
        if not hasattr(module, expected_class):
            found = [name for name in dir(module) if not name.startswith("_")]
            raise_error(
                "STR-002",
                file=str(file_path),
                expected_class=expected_class,
                found_classes=", ".join(found),
            )


def _check_params_structure(strategy_dir: Path) -> None:
    params_file = strategy_dir / "strategy_params.py"
    spec = importlib.util.spec_from_file_location("_preflight_params", params_file)
    if spec is None or spec.loader is None:
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys="<spec failed>",
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys=f"<import failed: {exc}>",
        )

    default = getattr(module, "DEFAULT_PARAMS", None)
    if not isinstance(default, dict):
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys="<DEFAULT_PARAMS missing or not a dict>",
        )

    missing_keys = [k for k in REQUIRED_PARAM_KEYS if k not in default]
    if missing_keys:
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys=", ".join(missing_keys),
        )

    # Each component sub-dict must include 'printlog'
    for component_key in REQUIRED_PARAM_KEYS:
        sub = default[component_key]
        if not isinstance(sub, dict) or "printlog" not in sub:
            raise_error(
                "PRM-001",
                file=str(params_file),
                function="DEFAULT_PARAMS",
                component_key=component_key,
            )


import ast as _ast
import json as _json
import re as _re


def _collect_json_declared_indicators(strategy_dir: Path) -> set[str]:
    """Return the set of indicator names declared in strategy_indicator_list.json."""
    path = strategy_dir / "strategy_indicator_list.json"
    try:
        payload = _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError):
        return set()
    indicators = payload.get("indicators", [])
    names: set[str] = set()
    for entry in indicators:
        if isinstance(entry, dict) and "name" in entry:
            names.add(str(entry["name"]))
        elif isinstance(entry, str):
            names.add(entry)
    return names


def _collect_code_referenced_strings(strategy_dir: Path) -> set[str]:
    """Heuristic: scan string literals in entry/exit/risk/sizer.py that look
    like indicator-name-style tokens (letters + digits + underscores, no
    spaces/punctuation)."""
    pattern = _re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    referenced: set[str] = set()
    for file_name in EXPECTED_CLASSES:  # entry.py, exit.py, risk.py, sizer.py
        path = strategy_dir / file_name
        if not path.exists():
            continue
        try:
            tree = _ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                s = node.value
                if pattern.match(s) and len(s) >= 3:
                    referenced.add(s)
    return referenced


def _check_indicator_casing(strategy_dir: Path) -> None:
    """Raise IND-001 if any code-referenced string matches a JSON-declared
    indicator when case-folded, but not exactly."""
    declared = _collect_json_declared_indicators(strategy_dir)
    referenced = _collect_code_referenced_strings(strategy_dir)
    declared_lower = {n.lower(): n for n in declared}
    for code_name in sorted(referenced):  # sorted for deterministic error ordering
        lower = code_name.lower()
        if lower in declared_lower and code_name != declared_lower[lower]:
            raise_error(
                "IND-001",
                code_name=code_name,
                json_name=declared_lower[lower],
            )


def preflight(strategy_dir) -> None:
    """Run all preflight checks against a strategy directory.

    Raises on the first failure; callers should surface the resulting
    ``EchelonError`` verbatim (its ``__str__`` already renders
    what/why/fix/context/docs_url).
    """
    strategy_dir = Path(strategy_dir)
    _check_required_files(strategy_dir)
    _check_required_classes(strategy_dir)
    _check_params_structure(strategy_dir)
    _check_indicator_casing(strategy_dir)
