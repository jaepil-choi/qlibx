"""BacktestConfig — what to backtest and where to find/store data."""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


class BacktestConfig(BaseModel):
    """Configuration for a single backtest run."""

    model_config = {"arbitrary_types_allowed": True}

    start_date: str = Field(..., description='Backtest start, "YYYY-MM-DD"')
    end_date: str = Field(..., description='Backtest end, "YYYY-MM-DD"')
    is_end_date: Optional[str] = Field(default=None)
    oos_start_date: Optional[str] = Field(default=None)
    strategy_dir: Path = Field(...)
    market_data_dir: Path = Field(...)
    indicator_dir: Path = Field(...)
    results_dir: Path = Field(...)
    max_drawdown_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    market_research_end_date: Optional[str] = None

    @field_validator("start_date", "end_date", "is_end_date", "oos_start_date",
                     "market_research_end_date")
    @classmethod
    def _validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            _parse_date(v)
        except ValueError as e:
            raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {v}") from e
        return v

    @model_validator(mode="after")
    def _validate_date_range(self) -> "BacktestConfig":
        start = _parse_date(self.start_date)
        end = _parse_date(self.end_date)
        if end < start:
            raise ValueError(
                f"end_date ({self.end_date}) must be >= start_date ({self.start_date})"
            )
        return self

    @model_validator(mode="after")
    def _derive_oos_start(self) -> "BacktestConfig":
        if self.is_end_date and not self.oos_start_date:
            is_end = _parse_date(self.is_end_date)
            self.oos_start_date = (is_end + timedelta(days=1)).isoformat()
        return self
