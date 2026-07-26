from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Mapping

import pandas as pd


def scaled_returns(
    datasets: Mapping[str, pd.DataFrame],
    *,
    scale: float,
    audit_path: str,
) -> pd.DataFrame:
    """Return a deterministic alpha and leave an observable invocation audit."""

    _reject_forbidden_execution()
    _record_invocation(Path(audit_path))
    return datasets["returns"].astype(float) * float(scale)


def synchronized_scaled_returns(
    datasets: Mapping[str, pd.DataFrame],
    *,
    scale: float,
    audit_path: str,
    marker_dir: str,
    marker_name: str,
    peer_marker_name: str,
    timeout_seconds: float = 5.0,
) -> pd.DataFrame:
    """Require two strategy calls to overlap without assuming threads or processes."""

    _reject_forbidden_execution()
    _record_invocation(Path(audit_path))
    markers = Path(marker_dir)
    markers.mkdir(parents=True, exist_ok=True)
    (markers / marker_name).touch()
    peer = markers / peer_marker_name
    deadline = time.monotonic() + timeout_seconds
    while not peer.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("strategy batch did not execute concurrently")
        time.sleep(0.01)
    return datasets["returns"].astype(float) * float(scale)


def _reject_forbidden_execution() -> None:
    if os.environ.get("KWAM_TEST_FORBID_ALPHA_EXECUTION") == "1":
        raise AssertionError("stored-run consumer re-executed an alpha strategy")


def _record_invocation(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\n")
