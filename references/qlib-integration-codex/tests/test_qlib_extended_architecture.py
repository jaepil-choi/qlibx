from __future__ import annotations

import ast
from pathlib import Path

import qlib_extended


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "qlib_extended"


def test_public_surface_is_limited_to_application_use_cases() -> None:
    assert set(qlib_extended.__all__) == {
        "ConfigurationError",
        "build_enhanced_index_attribution",
        "build_signed_attribution",
        "build_ensemble",
        "create_report",
        "open_run_catalog",
        "run_strategy_batch",
    }


def test_core_use_cases_do_not_import_storage_or_backend_implementations() -> None:
    forbidden = {"duckdb", "matplotlib", "qlib", "kwam_qlib_backend"}
    for name in ("runner.py", "planning.py", "ensemble.py"):
        imports = _imports(PACKAGE_ROOT / name)
        assert not imports.intersection(forbidden), (name, imports.intersection(forbidden))


def test_cli_contains_no_dataframe_storage_or_backend_dependencies() -> None:
    imports = _imports(PACKAGE_ROOT / "cli.py")
    assert not imports.intersection(
        {"duckdb", "matplotlib", "numpy", "pandas", "qlib", "kwam_qlib_backend"}
    )


def test_new_package_has_no_src_or_test_dependency_and_files_stay_focused() -> None:
    for path in PACKAGE_ROOT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "kwam_enhanced_index" not in source
        assert "test_support" not in source
        assert len(source.splitlines()) <= 350, f"split responsibilities in {path.name}"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names
