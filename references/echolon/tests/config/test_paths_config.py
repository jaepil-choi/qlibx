"""PathsConfig — single source of truth for library-owned directory layout."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from echolon.config.paths_config import PathsConfig

# Five tests below use Unix-style absolute paths (`/srv/shared/market`)
# as override fixtures. On Windows, `Path("/srv/...")` resolves to a
# drive-relative path (e.g. `D:\srv\...`) so the comparison fails. The
# tests verify Pydantic Settings behavior (env var precedence, .env
# loading, explicit-kwarg precedence) — that behavior is itself
# platform-portable; only the test fixtures aren't. Skip on Windows
# rather than rewrite the fixtures with platform-conditional paths.
_skip_on_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="fixture uses Unix-style absolute paths; behavior under test is platform-portable",
)


def test_from_project_root_conventional_layout(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    assert paths.project_root == tmp_path.resolve()
    assert paths.session_dir == tmp_path / "session"
    assert paths.workspace_dir == tmp_path / "workspace"
    assert paths.output_dir == tmp_path / "output"
    assert paths.raw_data_dir == tmp_path / "data"
    assert paths.market_data_dir == tmp_path / "workspace" / "data" / "market_data"
    assert paths.indicators_research_dir == tmp_path / "workspace" / "data" / "indicators" / "research"
    assert paths.indicators_backtest_dir == tmp_path / "workspace" / "data" / "indicators" / "backtest"
    # Flat OSS layout (host apps with iteration-loop layouts override these).
    assert paths.strategy_code_dir == tmp_path / "workspace" / "strategy" / "baseline"
    assert paths.backtest_results_dir == tmp_path / "workspace" / "backtest"
    assert paths.best_params_file == tmp_path / "workspace" / "strategy" / "baseline" / "selected_robust_trial.json"
    assert paths.deploy_config_file == tmp_path / "session" / "deploy_config.json"


def test_explicit_override(tmp_path: Path):
    paths = PathsConfig.from_project_root(
        tmp_path,
        market_data_dir=tmp_path / "custom_md",
    )
    assert paths.market_data_dir == tmp_path / "custom_md"
    # Non-overridden stays conventional
    assert paths.raw_data_dir == tmp_path / "data"


def test_all_paths_are_absolute(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    for name, value in paths.model_dump().items():
        if isinstance(value, Path):
            assert value.is_absolute(), f"{name} must be absolute; got {value}"


def test_string_accepted_at_construction(tmp_path: Path):
    paths = PathsConfig.from_project_root(str(tmp_path))
    assert isinstance(paths.project_root, Path)


def test_missing_required_root_raises():
    with pytest.raises(ValidationError):
        PathsConfig()  # project_root is required


def test_platformdirs_factory(monkeypatch):
    """Optional factory for pip-installed usage; uses platformdirs if available."""
    pytest.importorskip("platformdirs")
    paths = PathsConfig.from_platformdirs("echolon-test")
    assert paths.project_root.is_absolute()
    assert "echolon-test" in str(paths.project_root)


def test_from_env_with_env_var(tmp_path: Path, monkeypatch):
    """from_env() respects ECHOLON_PROJECT_ROOT."""
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    paths = PathsConfig.from_env()
    assert paths.project_root == tmp_path.resolve()


def test_from_env_falls_back_to_cwd(tmp_path: Path, monkeypatch):
    """from_env() falls back to cwd when env var is unset OR empty."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    paths = PathsConfig.from_env()
    assert paths.project_root == tmp_path.resolve()

    # Empty string env var also falls back.
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", "")
    paths = PathsConfig.from_env()
    assert paths.project_root == tmp_path.resolve()


def test_from_env_reflects_cwd_changes_after_import(tmp_path: Path, monkeypatch):
    """from_env() re-reads env + cwd on every call (not cached at import)."""
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert PathsConfig.from_env().project_root == tmp_path.resolve()

    other = tmp_path.parent
    monkeypatch.chdir(other)
    assert PathsConfig.from_env().project_root == other.resolve()


def test_from_env_custom_env_var(tmp_path: Path, monkeypatch):
    """from_env() honors a custom env var name."""
    monkeypatch.setenv("MY_ROOT", str(tmp_path))
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    paths = PathsConfig.from_env(env_var="MY_ROOT")
    assert paths.project_root == tmp_path.resolve()


def test_unknown_override_rejected(tmp_path: Path):
    """Typo'd override keys must raise ValidationError, not be silently dropped."""
    with pytest.raises(ValidationError):
        PathsConfig.from_project_root(tmp_path, markte_data_dir=tmp_path / "x")


def test_relative_override_resolved(tmp_path: Path, monkeypatch):
    """Relative-path overrides are absolutised (against cwd, per Pydantic's semantics)."""
    monkeypatch.chdir(tmp_path)
    paths = PathsConfig.from_project_root(tmp_path, market_data_dir="rel/md")
    assert paths.market_data_dir.is_absolute()
    assert paths.market_data_dir == (tmp_path / "rel" / "md").resolve()


def test_string_override_coerced_to_path(tmp_path: Path):
    """String overrides are coerced to Path by Pydantic's native type handling."""
    paths = PathsConfig.from_project_root(tmp_path, market_data_dir=str(tmp_path / "x"))
    assert isinstance(paths.market_data_dir, Path)
    assert paths.market_data_dir == tmp_path / "x"


# ---------------------------------------------------------------------------
# from_file — declarative JSON config (item-2 OSS friendliness)
# ---------------------------------------------------------------------------

def test_from_file_relative_paths_resolve_against_json_parent(tmp_path: Path):
    """Relative paths in the JSON resolve against the JSON file's parent dir
    so a checked-in path_config.json works regardless of cwd."""
    import json
    cfg_dir = tmp_path / "myproject"
    cfg_dir.mkdir()
    (cfg_dir / "echolon-paths.json").write_text(json.dumps({
        "project_root": ".",
        "market_data_dir": "data",
        "raw_data_dir": "data",
        "indicators_backtest_dir": "workspace/indicators",
    }))
    paths = PathsConfig.from_file(cfg_dir / "echolon-paths.json")
    assert paths.project_root == cfg_dir.resolve()
    assert paths.market_data_dir == (cfg_dir / "data").resolve()
    assert paths.raw_data_dir == (cfg_dir / "data").resolve()
    assert paths.indicators_backtest_dir == (cfg_dir / "workspace" / "indicators").resolve()


def test_from_file_absolute_paths_kept_as_is(tmp_path: Path):
    import json
    abs_data = tmp_path / "shared_data"
    abs_data.mkdir()
    cfg = tmp_path / "p.json"
    cfg.write_text(json.dumps({
        "project_root": str(tmp_path),
        "market_data_dir": str(abs_data),
    }))
    paths = PathsConfig.from_file(cfg)
    assert paths.market_data_dir == abs_data.resolve()


def test_from_file_missing_project_root_raises(tmp_path: Path):
    import json
    cfg = tmp_path / "p.json"
    cfg.write_text(json.dumps({"market_data_dir": "/x"}))
    with pytest.raises(ValueError, match="project_root"):
        PathsConfig.from_file(cfg)


def test_from_file_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        PathsConfig.from_file(tmp_path / "does_not_exist.json")


def test_from_file_unknown_field_rejected(tmp_path: Path):
    """Typo'd field name in JSON should fail loudly via Pydantic."""
    import json
    cfg = tmp_path / "p.json"
    cfg.write_text(json.dumps({
        "project_root": str(tmp_path),
        "markte_data_dir": str(tmp_path / "x"),  # typo
    }))
    with pytest.raises(ValidationError):
        PathsConfig.from_file(cfg)


# ---------------------------------------------------------------------------
# Per-field env var overrides (task 4 — pydantic-settings migration)
# ---------------------------------------------------------------------------

@_skip_on_windows
def test_per_field_env_var_overrides_market_data_dir(tmp_path: Path, monkeypatch):
    """ECHOLON_MARKET_DATA_DIR overrides the convention default while other
    fields continue to follow project_root convention."""
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ECHOLON_MARKET_DATA_DIR", "/srv/shared/market")
    paths = PathsConfig.from_env()
    assert paths.market_data_dir == Path("/srv/shared/market")
    # Non-overridden fields still follow convention
    assert paths.raw_data_dir == tmp_path.resolve() / "data"


@_skip_on_windows
def test_per_field_env_var_overrides_multiple_fields(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ECHOLON_MARKET_DATA_DIR", "/srv/md")
    monkeypatch.setenv("ECHOLON_RAW_DATA_DIR", "/srv/raw")
    monkeypatch.setenv("ECHOLON_INDICATORS_BACKTEST_DIR", "/scratch/ind")
    paths = PathsConfig.from_env()
    assert paths.market_data_dir == Path("/srv/md")
    assert paths.raw_data_dir == Path("/srv/raw")
    assert paths.indicators_backtest_dir == Path("/scratch/ind")


@_skip_on_windows
def test_dotenv_file_loaded_from_cwd(tmp_path: Path, monkeypatch):
    """.env in cwd is auto-loaded when constructing via PathsConfig() / from_env()."""
    (tmp_path / ".env").write_text(
        f"ECHOLON_PROJECT_ROOT={tmp_path}\n"
        f"ECHOLON_MARKET_DATA_DIR=/srv/shared/from_dotenv\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("ECHOLON_MARKET_DATA_DIR", raising=False)
    paths = PathsConfig()
    assert paths.market_data_dir == Path("/srv/shared/from_dotenv")
    assert paths.project_root == tmp_path.resolve()


@_skip_on_windows
def test_explicit_kwarg_beats_env_var(tmp_path: Path, monkeypatch):
    """Explicit kwarg to ``from_project_root`` wins over env var.

    ``from_project_root`` disables .env loading and applies the kwarg verbatim;
    the env var would otherwise be the precedence layer below explicit kwargs."""
    monkeypatch.setenv("ECHOLON_MARKET_DATA_DIR", "/from/env")
    paths = PathsConfig.from_project_root(tmp_path, market_data_dir="/from/kwarg")
    assert paths.market_data_dir == Path("/from/kwarg")


@_skip_on_windows
def test_env_beats_dotenv_file(tmp_path: Path, monkeypatch):
    """Process env var wins over the .env file (standard Pydantic Settings precedence)."""
    (tmp_path / ".env").write_text(
        f"ECHOLON_PROJECT_ROOT={tmp_path}\n"
        f"ECHOLON_MARKET_DATA_DIR=/from/dotenv\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHOLON_MARKET_DATA_DIR", "/from/process_env")
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    paths = PathsConfig()
    assert paths.market_data_dir == Path("/from/process_env")


def test_unknown_env_var_under_prefix_silently_skipped(tmp_path: Path, monkeypatch):
    """Standard Pydantic Settings behavior: env vars under the prefix that
    don't match a declared field are silently skipped. This is a known
    tradeoff — typo'd env vars don't fail loudly. Users wanting strict
    validation should prefer JSON config + ``from_file()`` (which DOES
    reject unknown fields via ``extra='forbid'``)."""
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ECHOLON_MARKTE_DATA_DIR", "/x")  # typo: markte
    paths = PathsConfig.from_env()  # No raise — typo'd var ignored.
    # Convention default applies for the actual market_data_dir field.
    assert paths.market_data_dir == tmp_path.resolve() / "workspace" / "data" / "market_data"
