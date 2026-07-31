"""Data-layer entry points must accept an injected PathsConfig."""
import inspect
import typing

from echolon.config.paths_config import PathsConfig
from echolon.data.backtest_data import run_data_pipeline
from echolon.data.live_data import run_live_data_update


def _accepts_paths(func) -> bool:
    sig = inspect.signature(func)
    if "paths" not in sig.parameters:
        return False
    annotation = sig.parameters["paths"].annotation
    # Accept either PathsConfig or Optional[PathsConfig] / PathsConfig | None.
    if annotation is PathsConfig:
        return True
    # PEP 604 or typing.Optional — get the non-None args.
    args = typing.get_args(annotation)
    return PathsConfig in args


def test_run_data_pipeline_accepts_paths():
    assert _accepts_paths(run_data_pipeline)


def test_run_live_data_update_accepts_paths():
    assert _accepts_paths(run_live_data_update)


def test_no_module_level_forbidden_settings_imports_anywhere():
    """No module in echolon/ may import path constants from settings at top level,
    except echolon/config/settings.py (the source) and files explicitly carrying
    a `# noqa: F401 — deprecated, use PathsConfig injection` marker on the line."""
    import ast
    import pathlib

    forbidden = {
        "RAW_DATA_DIR", "MARKET_DATA_DIR", "INDICATOR_DIR",
        "PROJECT_ROOT", "WORKSPACE_DIR", "OUTPUT_DIR", "SESSION_DIR",
        "INDICATORS_BACKTEST_DIR", "INDICATORS_RESEARCH_DIR",
        "PLATFORM_AGNOSTIC_DIR", "BEST_PARAMS_FILE", "BACKTEST_RESULTS_DIR",
        "STRATEGY_LOG_DIR", "DEPLOY_CONFIG_DIR",
    }
    base = pathlib.Path(__file__).resolve().parent.parent.parent / "echolon"
    offenders: list[tuple[str, list[str]]] = []
    for py in base.rglob("*.py"):
        # The source file itself defines these — skip.
        if py == base / "config" / "settings.py":
            continue
        src_lines = py.read_text(encoding="utf-8").splitlines()
        tree = ast.parse("\n".join(src_lines))
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "echolon.config.settings":
                continue
            # Check if this import line has the deprecation shim marker.
            # node.lineno is 1-indexed.
            line = src_lines[node.lineno - 1] if node.lineno - 1 < len(src_lines) else ""
            if "# noqa: F401 — deprecated, use PathsConfig injection" in line:
                continue
            leaked = sorted({alias.name for alias in node.names} & forbidden)
            if leaked:
                offenders.append((str(py.relative_to(base)), leaked))
    assert not offenders, f"module-level settings imports: {offenders}"
