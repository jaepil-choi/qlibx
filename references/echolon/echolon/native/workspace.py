"""Workspace marker file (.echolon-workspace.json) — write/read/walk-up.

Materialized by `echolon hello` and `echolon init`. Consumed by
`echolon backtest <strategy_dir>` to recover the trading context
(market, instrument, date range) plus any PathsConfig overrides
recorded under the ``paths`` field.

The file also serves as the workspace-root marker for walk-up
discovery — `find_workspace_root(path)` walks up from any directory
looking for it.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional, Tuple

WORKSPACE_MARKER = ".echolon-workspace.json"


class WorkspaceNotFoundError(FileNotFoundError):
    """Raised when no workspace marker is found by walking up from a path."""


def write_marker(
    workspace: Path,
    *,
    market: str,
    instrument: str,
    instrument_code: str,
    frequency: str,
    bar_size: str,
    date_range: Tuple[str, str],
    data_source: str,
    initial_capital: float,
    paths: Optional[dict] = None,
) -> Path:
    """Write the workspace marker. Returns the path written.

    Args:
        paths: Optional dict of relative-path overrides for ``PathsConfig``
            (``market_data_dir``, ``raw_data_dir``,
            ``indicators_backtest_dir``, ...). Resolved against the workspace
            root by ``echolon backtest``.
    """
    from echolon import __version__ as _ver

    payload = {
        "echolon_version": _ver,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "instrument": instrument,
        "instrument_code": instrument_code,
        "frequency": frequency,
        "bar_size": bar_size,
        "date_range": list(date_range),
        "data_source": data_source,
        "initial_capital": initial_capital,
    }
    if paths:
        payload["paths"] = {k: str(v) for k, v in paths.items()}
    out = Path(workspace) / WORKSPACE_MARKER
    out.write_text(json.dumps(payload, indent=2))
    return out


def read_marker(workspace: Path) -> dict:
    """Return the parsed marker. Raises FileNotFoundError if absent."""
    return json.loads((Path(workspace) / WORKSPACE_MARKER).read_text())


def find_workspace_root(start: Path) -> Path:
    """Walk up from ``start`` to find the directory containing a workspace
    marker. Raises WorkspaceNotFoundError if none is found.
    """
    current = Path(start).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / WORKSPACE_MARKER).is_file():
            return candidate
    raise WorkspaceNotFoundError(
        f"No {WORKSPACE_MARKER} found in {start} or any parent directory. "
        f"Run `echolon hello` or `echolon init <workspace>` first."
    )
