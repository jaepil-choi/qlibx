"""PathsConfig — single source of truth for echolon directory layout.

A PyPI library must not bind its filesystem layout to the user's cwd at
import time. Callers construct one PathsConfig and inject it at the
library's public entry points (``run_data_pipeline``, ``run_backtest``,
``run_indicator_calculation``, etc.).

Configuration sources (precedence: highest first):

1. **Explicit kwargs** — ``PathsConfig(project_root=..., market_data_dir=...)``
2. **Env vars** — ``ECHOLON_<FIELD>`` (e.g. ``ECHOLON_MARKET_DATA_DIR``)
3. **`.env` file** — auto-loaded from cwd (or ``env_file=`` override)
4. **Convention defaults** — derived from ``project_root`` via
   ``<root>/{session,workspace,output,data}`` layout

Typical usage from a host project::

    from echolon.config.paths_config import PathsConfig
    paths = PathsConfig.from_project_root(Path(__file__).parent.parent)
    run_data_pipeline(ctx, paths=paths)

Pip-installed end-users without a project layout::

    paths = PathsConfig.from_platformdirs("echolon")

Operators wanting per-field env overrides::

    $ export ECHOLON_MARKET_DATA_DIR=/srv/shared/market
    $ echolon backtest single ./strategy/baseline/

Hand-edited declarative config::

    paths = PathsConfig.from_file("echolon-paths.json")
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathsConfig(BaseSettings):
    """Every directory and file path echolon writes to or reads from.

    Each field has a corresponding ``ECHOLON_<FIELD>`` env var; fields left
    unset (and not supplied via env / .env) default to the convention rooted
    at ``project_root``.
    """

    model_config = SettingsConfigDict(
        env_prefix="ECHOLON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        # Don't fall back to JSON parsing for str→Path; treat env values as
        # literal path strings even when they look like JSON arrays.
        env_parse_none_str=None,
    )

    # Root — required (only field with no convention default).
    project_root: Path

    # All others optional; filled by the validator below from project_root.
    session_dir: Optional[Path] = None
    workspace_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    raw_data_dir: Optional[Path] = None

    market_data_dir: Optional[Path] = None
    indicators_research_dir: Optional[Path] = None
    indicators_backtest_dir: Optional[Path] = None

    current_dir: Optional[Path] = None
    strategy_code_dir: Optional[Path] = None
    backtest_results_dir: Optional[Path] = None
    current_analysis_dir: Optional[Path] = None

    best_params_file: Optional[Path] = None
    deploy_config_file: Optional[Path] = None

    @model_validator(mode="after")
    def _fill_conventions_and_absolutise(self) -> "PathsConfig":
        """Apply convention defaults for any field left unset, then absolutise.

        Default layout (flat, OSS-friendly)::

            <root>/
              data/                           # raw_data_dir
              workspace/
                data/market_data/             # market_data_dir
                data/indicators/backtest/     # indicators_backtest_dir
                backtest/                     # backtest_results_dir
                strategy/baseline/            # strategy_code_dir
              output/                         # output_dir
              session/                        # session_dir

        Host apps that want an iteration-loop layout (e.g. one where each
        refinement cycle works under ``workspace/current/{code,backtest,
        analysis}/`` and is then archived) override the relevant fields when
        constructing PathsConfig.
        """
        root = Path(self.project_root).absolute()
        workspace = self.workspace_dir or (root / "workspace")
        indicators = workspace / "data" / "indicators"
        current = self.current_dir or (workspace / "current")
        strategy_code = self.strategy_code_dir or (workspace / "strategy" / "baseline")

        # Defaults dict — only fills None fields so explicit kwargs / env vars
        # stay authoritative.
        defaults: dict[str, Path] = {
            "project_root": root,
            "session_dir": root / "session",
            "workspace_dir": workspace,
            "output_dir": root / "output",
            "raw_data_dir": root / "data",
            "market_data_dir": workspace / "data" / "market_data",
            "indicators_research_dir": indicators / "research",
            "indicators_backtest_dir": indicators / "backtest",
            "current_dir": current,
            "strategy_code_dir": strategy_code,
            "backtest_results_dir": workspace / "backtest",
            "current_analysis_dir": current / "analysis",
            "best_params_file": strategy_code / "selected_robust_trial.json",
            "deploy_config_file": root / "session" / "deploy_config.json",
        }
        for name, default in defaults.items():
            current_value = getattr(self, name)
            if current_value is None:
                setattr(self, name, default)
            elif isinstance(current_value, Path) and not current_value.is_absolute():
                setattr(self, name, current_value.resolve())
        return self

    @classmethod
    def from_project_root(cls, project_root: Path | str, **overrides: Path | str) -> "PathsConfig":
        """Build from conventional <root>/{session,workspace,output,data} layout.

        Any field can be overridden by keyword (e.g. ``market_data_dir=...``).
        Env vars are NOT consulted for fields supplied here — the explicit
        kwarg wins. Use ``PathsConfig()`` directly if you want env / .env
        layered with explicit kwargs.
        """
        # _env_file=None disables .env loading so explicit kwargs aren't
        # surprised by stray .env in cwd. Callers wanting env layering should
        # call ``PathsConfig(project_root=..., **overrides)`` directly.
        return cls(
            project_root=Path(project_root).absolute(),
            _env_file=None,
            **{k: Path(v) for k, v in overrides.items()},
        )

    @classmethod
    def from_env(cls, env_var: str = "ECHOLON_PROJECT_ROOT") -> "PathsConfig":
        """Resolve project root from env var (or cwd) and build config.

        Per-field env vars (``ECHOLON_MARKET_DATA_DIR`` etc.) and ``.env``
        files are consulted automatically by Pydantic Settings — call this
        only when no explicit ``paths=`` was injected upstream.

        ``env_var`` lets callers customize the project-root variable name;
        when it matches the default (``ECHOLON_PROJECT_ROOT``), pydantic-settings
        picks it up natively.
        """
        import os
        root = os.getenv(env_var)
        if root:
            # Caller pinned the root explicitly; .env layering is disabled
            # so this single env var wins deterministically.
            return cls(project_root=root, _env_file=None)
        # Let pydantic-settings build from env / .env / per-field env vars.
        # If project_root isn't derivable from any of those, fall back to cwd.
        try:
            return cls()
        except Exception:
            return cls(project_root=Path.cwd(), _env_file=None)

    @classmethod
    def from_file(cls, json_path: Path | str) -> "PathsConfig":
        """Build from a JSON config file with field overrides.

        The JSON file MUST contain a ``project_root`` key (absolute or
        relative to the JSON file's parent dir). Any other PathsConfig field
        may be supplied to override the project-root convention; missing
        fields use the conventions baked into ``from_project_root``.

        Relative paths in the file are resolved against the JSON file's
        parent directory so a checked-in ``path_config.json`` works
        regardless of cwd.

        Example ``echolon-paths.json``::

            {
                "project_root": ".",
                "market_data_dir": "data",
                "raw_data_dir": "data",
                "indicators_backtest_dir": "workspace/indicators"
            }

        Useful for end-users who want a hand-edited config file rather than
        env vars or a workspace marker.
        """
        import json
        json_path = Path(json_path).resolve()
        if not json_path.is_file():
            raise FileNotFoundError(
                f"PathsConfig.from_file: {json_path} does not exist"
            )
        payload = json.loads(json_path.read_text())
        if "project_root" not in payload:
            raise ValueError(
                f"PathsConfig.from_file: {json_path} must include 'project_root' "
                f"(absolute or relative to the file's parent dir)."
            )
        anchor = json_path.parent

        def _resolve(value: str) -> Path:
            p = Path(value)
            return p if p.is_absolute() else (anchor / p).resolve()

        project_root = _resolve(payload.pop("project_root"))
        overrides = {k: _resolve(v) for k, v in payload.items()}
        return cls.from_project_root(project_root, **overrides)

    @classmethod
    def from_platformdirs(cls, app_name: str = "echolon") -> "PathsConfig":
        """Build using platformdirs (XDG on Linux, %APPDATA% on Windows).

        platformdirs ships as a hard dep; suitable for pip-installed
        end-users without a project layout of their own.
        """
        try:
            from platformdirs import user_data_dir
        except ImportError as exc:
            raise ImportError(
                "PathsConfig.from_platformdirs requires `platformdirs`, "
                "which ships as a hard dep with echolon — a missing import "
                "suggests a broken install. Try `pip install --force-reinstall echolon`."
            ) from exc
        return cls.from_project_root(user_data_dir(app_name, ensure_exists=False))
