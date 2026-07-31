"""OptunaConfig — Optuna optimization settings."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class OptunaConfig(BaseModel):
 """Optuna hyperparameter optimization settings."""

 n_trials: int = Field(default=100, ge=1)
 n_trials_debug: int = Field(default=20, ge=1)
 n_jobs: int = Field(default=-1)
 timeout: Optional[int] = Field(default=None, ge=1)
 target: Literal[
 "sharpe_ratio", "total_return", "annual_return",
 "drawdown", "multi_objective",
 ] = Field(default="sharpe_ratio")
 aggressive_memory_management: bool = Field(default=False)
 enhanced_monitoring: bool = Field(default=True)
