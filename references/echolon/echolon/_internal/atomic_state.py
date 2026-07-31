"""Atomic state file writes + heartbeat emission.

Guarantees readers (e.g., goingmerry's dashboard poster) never observe partial
JSON files, even if the writer is killed mid-write. Uses the classic
tmp-file-then-rename pattern (POSIX rename is atomic for same-filesystem moves).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_SCHEMA_VERSION = "1.0"
HEARTBEAT_SCHEMA_VERSION = "1.0"


def write_state_atomically(path: str, payload: dict) -> None:
    """Write payload to `path` atomically via tmp-then-rename.

    Injects `schema_version` only if not already present on the payload.
    """
    if "schema_version" not in payload:
        payload = {"schema_version": STATE_SCHEMA_VERSION, **payload}
    path_p = Path(path)
    path_p.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path_p.with_suffix(path_p.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, path_p)  # POSIX-atomic on same FS


def update_heartbeat(workspace_deploy_dir: str, slots_alive: list[str]) -> None:
    """Write/overwrite heartbeat.json in the workspace deploy dir.

    Called after each trading cycle. Readers alert on staleness
    (>2× cycle interval) to detect a hung trading process.
    """
    path_p = Path(workspace_deploy_dir) / "heartbeat.json"
    payload = {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "last_cycle_ts": datetime.now(timezone.utc).isoformat(),
        "slots_alive": sorted(slots_alive),
    }
    write_state_atomically(str(path_p), payload)
