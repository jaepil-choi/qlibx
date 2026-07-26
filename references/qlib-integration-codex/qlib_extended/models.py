from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_kind: str
    strategy_id: str
    status: str
    config_fingerprint: str
    dataset_fingerprint: str
    strategy_fingerprint: str
    parent_run_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyRun:
    strategy_id: str
    alpha_run_id: str
    backtest_run_id: str
    status: str
    cached: bool


@dataclass(frozen=True)
class BatchOutcome:
    runs: tuple[StrategyRun, ...]


@dataclass(frozen=True)
class ReportResult:
    backtest_run_ids: tuple[str, ...]
    html_path: Path
    png_paths: tuple[Path, ...] = ()

    @property
    def files(self) -> tuple[Path, ...]:
        return (self.html_path, *self.png_paths)


@dataclass(frozen=True)
class SignedAttributionResult:
    backtest_run_id: str
    alpha_run_id: str
    instrument_daily: pd.DataFrame
    member_daily: pd.DataFrame
    summary_daily: pd.DataFrame


@dataclass(frozen=True)
class EnhancedIndexAttributionResult:
    backtest_run_id: str
    alpha_run_id: str
    member_intent_daily: pd.DataFrame
    constituent_daily: pd.DataFrame
    physical_daily: pd.DataFrame


@dataclass(frozen=True)
class ComputedStrategyRun:
    alpha: pd.DataFrame
    backtest_artifacts: Mapping[str, pd.DataFrame]
    backtest_metadata: Mapping[str, Any]
