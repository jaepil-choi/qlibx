"""Book backtest models."""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .nominal_schedule import NominalCycleSchedule
from .risk_policy import RiskPolicyBinding
from .schedule import ExecutionContractSchedule


class BookLifecycleContract(BaseModel):
    """Opt-in strict lifecycle and terminal-certification contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["book-lifecycle-contract/v1"] = "book-lifecycle-contract/v1"
    terminal_open_date: dt.date | None = None
    expected_nominal_cycle_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_cycle_ids(self) -> "BookLifecycleContract":
        if len(set(self.expected_nominal_cycle_ids)) != len(
            self.expected_nominal_cycle_ids
        ):
            raise ValueError("expected_nominal_cycle_ids must be unique")
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in self.expected_nominal_cycle_ids
        ):
            raise ValueError(
                "expected_nominal_cycle_ids must be lowercase SHA-256 identities"
            )
        return self


class BookBacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: dt.date
    end: dt.date
    initial_equity_rmb: float
    panel_snapshot: str
    panel_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        exclude_if=lambda value: value is None,
    )
    execution_contract_schedule: ExecutionContractSchedule | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    rebalance_mode: Literal["legacy", "nominal_cycle_schedule"] = Field(
        default="legacy",
        exclude_if=lambda value: value == "legacy",
    )
    nominal_cycle_schedule: NominalCycleSchedule | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    risk_policy_binding: RiskPolicyBinding | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    lifecycle_contract: BookLifecycleContract | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    commission_multiplier: float = Field(
        default=1.0,
        gt=0.0,
        exclude_if=lambda value: value == 1.0,
    )
    slippage_bps_by_instrument: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_execution_contract_schedule(self) -> "BookBacktestConfig":
        if not math.isfinite(self.commission_multiplier):
            raise ValueError("commission_multiplier must be finite")
        lifecycle = self.lifecycle_contract
        if lifecycle is not None:
            if self.rebalance_mode == "nominal_cycle_schedule":
                if not lifecycle.expected_nominal_cycle_ids:
                    raise ValueError(
                        "strict nominal lifecycle requires expected_nominal_cycle_ids"
                    )
                if lifecycle.terminal_open_date is not None:
                    raise ValueError(
                        "nominal strict lifecycle derives terminal_open_date from its "
                        "last expected cycle"
                    )
            else:
                if lifecycle.expected_nominal_cycle_ids:
                    raise ValueError(
                        "expected_nominal_cycle_ids require nominal-cycle rebalance mode"
                    )
                if lifecycle.terminal_open_date is None:
                    raise ValueError(
                        "non-nominal strict lifecycle requires terminal_open_date"
                    )
                if lifecycle.terminal_open_date != self.end:
                    raise ValueError(
                        "strict terminal_open_date must equal the backtest end date"
                    )
        if self.rebalance_mode == "legacy" and self.nominal_cycle_schedule is not None:
            raise ValueError(
                "nominal_cycle_schedule requires "
                "rebalance_mode='nominal_cycle_schedule'"
            )
        if (
            self.rebalance_mode == "nominal_cycle_schedule"
            and self.nominal_cycle_schedule is None
        ):
            raise ValueError(
                "rebalance_mode='nominal_cycle_schedule' requires "
                "nominal_cycle_schedule"
            )
        nominal_schedule = self.nominal_cycle_schedule
        if nominal_schedule is not None:
            if self.panel_manifest_sha256 is None:
                raise ValueError(
                    "panel_manifest_sha256 is required with a nominal-cycle schedule"
                )
            if self.panel_snapshot != nominal_schedule.source_panel_snapshot:
                raise ValueError(
                    "nominal-cycle schedule source_panel_snapshot does not match "
                    "BookBacktestConfig.panel_snapshot"
                )
            if (
                self.panel_manifest_sha256
                != nominal_schedule.source_panel_manifest_sha256
            ):
                raise ValueError(
                    "nominal-cycle schedule source_panel_manifest_sha256 does not "
                    "match BookBacktestConfig.panel_manifest_sha256"
                )
        schedule = self.execution_contract_schedule
        if schedule is None:
            return self
        if self.panel_manifest_sha256 is None:
            raise ValueError(
                "panel_manifest_sha256 is required with an execution contract schedule"
            )
        if self.panel_snapshot != schedule.source_panel_snapshot:
            raise ValueError(
                "execution contract schedule source_panel_snapshot does not match "
                "BookBacktestConfig.panel_snapshot"
            )
        if self.panel_manifest_sha256 != schedule.source_panel_manifest_sha256:
            raise ValueError(
                "execution contract schedule source_panel_manifest_sha256 does not "
                "match BookBacktestConfig.panel_manifest_sha256"
            )
        if self.start < schedule.start or self.end > schedule.end:
            raise ValueError(
                "execution contract schedule does not cover the requested config window"
            )
        return self


class EquityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    equity_rmb: float
    cash_rmb: float
    margin_used_rmb: float


class TradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    instrument: str
    contract: str
    side: str
    lots: float
    intended_price: float
    fill_price: float
    slippage_rmb: float
    commission_rmb: float
    close_today: bool
    realized_pnl_rmb: float
    position_after: float


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    net_sharpe: float
    ann_return_pct: float
    max_dd_pct: float
    n_trades: int
    fees_total_rmb: float
    slippage_total_rmb: float
    determinism_hash: str
    full_result_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EndingPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    instrument: str
    contract: str
    lots: float
    average_price: float
    opened_date: dt.date | None

    @model_validator(mode="after")
    def _validate_open_position(self) -> "EndingPosition":
        if not self.instrument or not self.contract:
            raise ValueError("ending position identities must be non-empty")
        if abs(self.lots) <= 1e-12:
            raise ValueError("ending_positions must omit flat positions")
        return self


class EndingPendingIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    instrument: str
    target_lots: float
    decision_date: dt.date
    eligible_fill_date: dt.date | None
    nominal_cycle_schedule_sha256: str | None
    cycle_id: str | None
    nominal_date: dt.date | None

    @model_validator(mode="after")
    def _validate_pending_identity(self) -> "EndingPendingIntent":
        if not self.instrument:
            raise ValueError("pending intent instrument must be non-empty")
        nominal_fields = (
            self.nominal_cycle_schedule_sha256,
            self.cycle_id,
            self.nominal_date,
            self.eligible_fill_date,
        )
        if any(value is not None for value in nominal_fields) and any(
            value is None for value in nominal_fields
        ):
            raise ValueError("pending nominal-cycle provenance must be complete")
        return self


class BookOutcome(BaseModel):
    """Replayable terminal state and certification result."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["book-outcome/v1"] = "book-outcome/v1"
    status: Literal[
        "VALID_COMPLETE",
        "LEGACY_UNCERTIFIED",
        "LIQUIDATED_HALT",
        "INSOLVENT_HALT",
        "LIQUIDATION_BLOCKED_HALT",
        "INVALID_INCOMPLETE",
    ]
    terminal_reason: str
    terminal_date: dt.date
    liquidation_trigger_date: dt.date | None = None
    liquidation_completion_date: dt.date | None = None
    trigger_cash_rmb: float | None = None
    trigger_equity_rmb: float | None = None
    trigger_margin_used_rmb: float | None = None
    ending_cash_rmb: float
    ending_equity_rmb: float
    ending_margin_used_rmb: float
    ending_positions: tuple[EndingPosition, ...]
    ending_pending_intents: tuple[EndingPendingIntent, ...]
    expected_nominal_cycle_ids: tuple[str, ...] = ()
    executed_nominal_cycle_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_terminal_truth(self) -> "BookOutcome":
        if not self.terminal_reason or self.terminal_reason != self.terminal_reason.strip():
            raise ValueError("terminal_reason must be non-empty and trimmed")
        if len(set(self.executed_nominal_cycle_ids)) != len(
            self.executed_nominal_cycle_ids
        ):
            raise ValueError("executed_nominal_cycle_ids must be unique")
        if len(set(self.expected_nominal_cycle_ids)) != len(
            self.expected_nominal_cycle_ids
        ):
            raise ValueError("expected_nominal_cycle_ids must be unique")
        for label, identities in (
            ("expected", self.expected_nominal_cycle_ids),
            ("executed", self.executed_nominal_cycle_ids),
        ):
            if any(
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in identities
            ):
                raise ValueError(f"{label} nominal cycle IDs must be lowercase SHA-256")
        position_instruments = tuple(row.instrument for row in self.ending_positions)
        if len(set(position_instruments)) != len(position_instruments):
            raise ValueError("ending_positions cannot repeat an instrument")
        pending_instruments = tuple(
            row.instrument for row in self.ending_pending_intents
        )
        if len(set(pending_instruments)) != len(pending_instruments):
            raise ValueError("ending_pending_intents cannot repeat an instrument")
        if self.ending_margin_used_rmb < -1e-8:
            raise ValueError("ending margin cannot be negative")
        liquidation_values = (
            self.liquidation_trigger_date,
            self.trigger_cash_rmb,
            self.trigger_equity_rmb,
            self.trigger_margin_used_rmb,
        )
        has_trigger = self.liquidation_trigger_date is not None
        if has_trigger != all(value is not None for value in liquidation_values):
            raise ValueError("liquidation trigger provenance must be all present or absent")
        if (
            self.liquidation_completion_date is not None
            and self.liquidation_trigger_date is None
        ):
            raise ValueError("liquidation completion requires a trigger")
        if self.liquidation_completion_date is not None:
            assert self.liquidation_trigger_date is not None
            if self.liquidation_completion_date <= self.liquidation_trigger_date:
                raise ValueError("liquidation completion must be after its trigger")
            if self.terminal_date != self.liquidation_completion_date:
                raise ValueError("completed liquidation terminal_date must equal completion")
        if (
            self.liquidation_trigger_date is not None
            and self.liquidation_trigger_date > self.terminal_date
        ):
            raise ValueError("liquidation trigger cannot follow terminal_date")

        flat = not self.ending_positions
        no_pending = not self.ending_pending_intents
        zero_margin = abs(self.ending_margin_used_rmb) <= 1e-8
        if flat and not math.isclose(
            self.ending_cash_rmb,
            self.ending_equity_rmb,
            rel_tol=0.0,
            abs_tol=1e-8,
        ):
            raise ValueError("flat ending state requires cash equal to equity")

        if self.status == "VALID_COMPLETE":
            if not (flat and no_pending and zero_margin):
                raise ValueError("VALID_COMPLETE requires a flat, reconciled ending state")
            if has_trigger or self.liquidation_completion_date is not None:
                raise ValueError("VALID_COMPLETE cannot contain liquidation provenance")
            if self.expected_nominal_cycle_ids != self.executed_nominal_cycle_ids:
                raise ValueError("VALID_COMPLETE requires every expected cycle exactly once")
            if self.ending_equity_rmb <= 0:
                raise ValueError("VALID_COMPLETE requires positive ending equity")
        elif self.status == "LIQUIDATED_HALT":
            if not has_trigger or self.liquidation_completion_date is None:
                raise ValueError("completed liquidation status requires trigger and completion")
            if not (flat and no_pending and zero_margin):
                raise ValueError("completed liquidation requires a flat ending state")
            if self.ending_equity_rmb <= 0:
                raise ValueError("non-insolvent liquidation requires positive ending equity")
        elif self.status == "INSOLVENT_HALT":
            if not (flat and no_pending and zero_margin):
                raise ValueError("INSOLVENT_HALT requires a flat ending state")
            if self.ending_equity_rmb > 0:
                raise ValueError("INSOLVENT_HALT requires non-positive ending equity")
            if has_trigger != (self.liquidation_completion_date is not None):
                raise ValueError(
                    "liquidation-caused insolvency requires trigger and completion together"
                )
        elif self.status == "LIQUIDATION_BLOCKED_HALT":
            if not has_trigger or self.liquidation_completion_date is not None:
                raise ValueError("blocked liquidation requires an uncompleted trigger")
            if flat:
                raise ValueError("blocked liquidation must retain at least one position")
            if not no_pending:
                raise ValueError("blocked liquidation cannot retain normal target intents")
        return self


class BookRuntimeManifest(BaseModel):
    """Canonical inputs needed to reproduce a full-result identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["book-runtime-manifest/v1"] = "book-runtime-manifest/v1"
    engine: Literal["DailyBookBacktester/v1"] = "DailyBookBacktester/v1"
    config: dict[str, Any]
    slippage_bps: float
    rebalance_weekday: int | None
    rebalance_interval_weeks: int
    stamp_duty_schedule: tuple[tuple[dt.date, float], ...] | None

    @model_validator(mode="after")
    def _validate_canonical_json(self) -> "BookRuntimeManifest":
        if self.rebalance_interval_weeks < 1:
            raise ValueError("rebalance_interval_weeks must be >= 1")
        try:
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime manifest must be canonical finite JSON") from exc
        return self


class BookResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]
    rebalance_records: list[dict] = Field(default_factory=list)
    daily_returns: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    runtime_manifest: BookRuntimeManifest
    outcome: BookOutcome
    summary: Summary
