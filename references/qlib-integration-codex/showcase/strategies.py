from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


def momentum_alpha(
    datasets: Mapping[str, pd.DataFrame], *, audit_path: str
) -> pd.DataFrame:
    _record_invocation(Path(audit_path), "momentum")
    return datasets["returns"].rolling(3, min_periods=1).mean()


def reversal_alpha(
    datasets: Mapping[str, pd.DataFrame], *, audit_path: str
) -> pd.DataFrame:
    _record_invocation(Path(audit_path), "reversal")
    return -datasets["returns"].rolling(2, min_periods=1).mean()


def _record_invocation(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{name}\n")
