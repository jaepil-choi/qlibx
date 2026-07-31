"""Validate a strategy directory against Echolon contracts."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from echolon.errors import EchelonError, ERROR_CATALOG


REQUIRED_FILES = (
    "strategy.py", "entry.py", "exit.py", "risk.py", "sizer.py",
    "strategy_params.py", "strategy_indicator_list.json",
)


EXPECTED_CLASSES = {
    "strategy.py": "strategy_main",
    "entry.py": "entry_rule",
    "exit.py": "exit_rule",
    "risk.py": "risk_manager",
    "sizer.py": "position_sizer",
}


def _make_error(code: str, **context_vars):
    entry = ERROR_CATALOG[code]
    try:
        fix = entry["fix_template"].format(**context_vars)
    except KeyError:
        fix = entry["fix_template"]
    return entry["class"](
        code=code, what=entry["what"], why=entry["why"], fix=fix,
        context=dict(context_vars),
        docs_url=f"https://github.com/dolphinquant/echolon/blob/master/echolon/native/errors/codes/{code}.md",
    )


def _check_required_files(strategy_dir: Path) -> list[EchelonError]:
    if not strategy_dir.is_dir():
        return [_make_error(
            "STR-001",
            strategy_dir=str(strategy_dir),
            missing_files=", ".join(REQUIRED_FILES),
        )]
    missing = [f for f in REQUIRED_FILES if not (strategy_dir / f).exists()]
    if missing:
        return [_make_error(
            "STR-001",
            strategy_dir=str(strategy_dir),
            missing_files=", ".join(missing),
        )]
    return []


def _check_classes_defined(strategy_dir: Path) -> list[EchelonError]:
    errors = []
    for filename, expected_class in EXPECTED_CLASSES.items():
        file_path = strategy_dir / filename
        if not file_path.exists():
            continue
        try:
            tree = ast.parse(file_path.read_text())
        except SyntaxError as e:
            errors.append(_make_error(
                "STR-002", file=filename, expected_class=expected_class,
                found_classes=f"SyntaxError: {e}",
            ))
            continue
        found = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if expected_class not in found:
            errors.append(_make_error(
                "STR-002", file=filename, expected_class=expected_class,
                found_classes=str(found) if found else "none",
            ))
    return errors


def _check_strategy_params(strategy_dir: Path) -> list[EchelonError]:
    errors = []
    params_path = strategy_dir / "strategy_params.py"
    if not params_path.exists():
        return []
    namespace: dict = {}
    try:
        exec(compile(params_path.read_text(), str(params_path), "exec"), namespace)
    except Exception as e:
        errors.append(_make_error(
            "PRM-002", file="strategy_params.py",
            missing_keys=f"import failed: {e}",
        ))
        return errors

    default_params = namespace.get("DEFAULT_PARAMS")
    if not isinstance(default_params, dict):
        errors.append(_make_error(
            "PRM-002", file="strategy_params.py",
            missing_keys="DEFAULT_PARAMS must be a dict",
        ))
        return errors

    required_keys = {"entry_params", "exit_params", "risk_params", "sizer_params"}
    missing = required_keys - default_params.keys()
    if missing:
        errors.append(_make_error(
            "PRM-002", file="strategy_params.py",
            missing_keys=", ".join(sorted(missing)),
        ))

    for comp_key in required_keys & default_params.keys():
        if not isinstance(default_params[comp_key], dict):
            continue
        if "printlog" not in default_params[comp_key]:
            errors.append(_make_error(
                "PRM-001", file="strategy_params.py",
                function="DEFAULT_PARAMS", component_key=comp_key,
            ))
    return errors


def validate_strategy_dir(strategy_dir: Path) -> list[EchelonError]:
    """Validate a strategy directory. Returns list of errors (empty = valid)."""
    strategy_dir = Path(strategy_dir)
    errors: list[EchelonError] = []
    errors.extend(_check_required_files(strategy_dir))
    errors.extend(_check_classes_defined(strategy_dir))
    errors.extend(_check_strategy_params(strategy_dir))
    return errors


@dataclass
class ValidationResult:
    """Structured return value for the programmatic validate_strategy API."""

    status: str  # "VALID" or "INVALID"
    errors: list[EchelonError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "VALID"


def validate_strategy(path: Union[str, Path]) -> ValidationResult:
    """Programmatic API: validate a strategy directory.

    Thin wrapper around validate_strategy_dir that returns a structured
    ValidationResult (status + errors) instead of a bare list.

    Args:
        path: Strategy directory path (str or Path).

    Returns:
        ValidationResult with .status == "VALID" if no errors, else "INVALID".
    """
    errs = validate_strategy_dir(Path(path))
    return ValidationResult(
        status="VALID" if not errs else "INVALID",
        errors=errs,
    )
