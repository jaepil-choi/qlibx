"""Public configuration for the current daily simulation profile."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from qlibx.execution import EtfInstrument, KrxExchangeConfig, StockInstrument
from qlibx.kernel.clock import require_aware
from qlibx.models import QlibxModel
from qlibx.operations import StrategyArtifactBinding
from qlibx.specs.constraints import MvpConstraintPolicy


class DailyAccountSeed(QlibxModel):
    """Initial authoritative state for one isolated daily simulation."""

    account_id: str = Field(min_length=1)
    base_currency: str = Field(min_length=3, max_length=3)
    initial_cash: float = Field(ge=0)


class DailyMarketBinding(QlibxModel):
    """Logical market roles consumed by the canonical daily profile."""

    market_dataset_id: str = Field(min_length=1)
    execution_price_role: str = Field(default="execution_price", min_length=1)
    valuation_price_role: str = Field(default="valuation_price", min_length=1)
    feedback_entry_limit: int = Field(default=256, gt=0)


ExecutableInstrument = Annotated[
    StockInstrument | EtfInstrument,
    Field(discriminator="kind"),
]

ExecutionTiming = Literal["next_session_close", "next_session_open"]


def _validate_environment(
    *,
    account: DailyAccountSeed,
    instruments: tuple[ExecutableInstrument, ...],
    exchange: KrxExchangeConfig,
) -> None:
    instrument_ids = tuple(item.instrument_id for item in instruments)
    if len(instrument_ids) != len(set(instrument_ids)):
        raise ValueError("daily simulation instruments must be unique")
    if any(item.exchange_id != exchange.exchange_id for item in instruments):
        raise ValueError("instrument exchange_id must match the daily exchange")
    if any(item.currency != account.base_currency for item in instruments):
        raise ValueError("instrument currency must match the Account base currency")
    if exchange.participation_rate is not None:
        raise ValueError("public daily simulation does not support volume participation")
    if exchange.impact_rate != 0:
        raise ValueError("public daily simulation does not support market impact")


def _validate_schedule(
    *,
    session_closes: tuple[datetime, ...],
    session_opens: tuple[datetime, ...],
    execution_timing: ExecutionTiming,
) -> None:
    closes = tuple(require_aware(value) for value in session_closes)
    opens = tuple(require_aware(value) for value in session_opens)
    if closes != tuple(sorted(set(closes))):
        raise ValueError("session_closes must be unique and sorted")
    if opens != tuple(sorted(set(opens))):
        raise ValueError("session_opens must be unique and sorted")
    if execution_timing == "next_session_open" and not opens:
        raise ValueError("next-session-open execution requires session_opens")
    if execution_timing == "next_session_close" and opens:
        raise ValueError("session_opens require next-session-open execution")


def _base_config_payload(
    *,
    account: DailyAccountSeed,
    instruments: tuple[ExecutableInstrument, ...],
    exchange: KrxExchangeConfig,
    market: DailyMarketBinding,
    execution_timing: ExecutionTiming,
    constraint_policy: MvpConstraintPolicy | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "spec_schema_version": 1,
        "account": account.model_dump(mode="json"),
        "instruments": [item.model_dump(mode="json") for item in instruments],
        "exchange": exchange.model_dump(mode="json"),
        "market": market.model_dump(mode="json"),
    }
    if execution_timing != "next_session_close":
        payload["execution_timing"] = execution_timing
    if constraint_policy is not None:
        payload["constraint_policy"] = constraint_policy.model_dump(mode="json")
    return payload


class DailySimulationSpec(QlibxModel):
    """Frozen public input for supported next-session close or open simulation."""

    spec_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    strategy_fingerprint: str = Field(min_length=1)
    account: DailyAccountSeed
    instruments: tuple[ExecutableInstrument, ...] = Field(min_length=1)
    exchange: KrxExchangeConfig
    market: DailyMarketBinding
    execution_timing: ExecutionTiming = "next_session_close"
    decision_times: tuple[datetime, ...]
    session_closes: tuple[datetime, ...] = Field(min_length=1)
    session_opens: tuple[datetime, ...] = ()
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = ()
    constraint_policy: MvpConstraintPolicy | None = None

    @model_validator(mode="after")
    def validate_current_daily_scope(self) -> "DailySimulationSpec":
        _validate_environment(
            account=self.account,
            instruments=self.instruments,
            exchange=self.exchange,
        )
        binding_roles = [binding.consumer_role for binding in self.artifact_bindings]
        if len(binding_roles) != len(set(binding_roles)):
            raise ValueError("daily Strategy artifact binding roles must be unique")

        decisions = tuple(require_aware(value) for value in self.decision_times)
        if decisions != tuple(sorted(set(decisions))):
            raise ValueError("decision_times must be unique and sorted")
        _validate_schedule(
            session_closes=self.session_closes,
            session_opens=self.session_opens,
            execution_timing=self.execution_timing,
        )
        return self

    def frozen_config_fingerprint(self) -> str:
        """Hash economic configuration separately from run schedule and run identity."""

        payload = _base_config_payload(
            account=self.account,
            instruments=self.instruments,
            exchange=self.exchange,
            market=self.market,
            execution_timing=self.execution_timing,
            constraint_policy=self.constraint_policy,
        )
        payload.update(
            {
            "strategy_fingerprint": self.strategy_fingerprint,
            }
        )
        if self.artifact_bindings:
            payload["artifact_bindings"] = [
                binding.model_dump(mode="json") for binding in self.artifact_bindings
            ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class FrozenDailyExecutionSpec(QlibxModel):
    """Frozen public input for exact DecisionIntent child execution."""

    spec_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    parent_decision_artifact_ids: tuple[str, ...] = Field(min_length=1)
    account: DailyAccountSeed
    instruments: tuple[ExecutableInstrument, ...] = Field(min_length=1)
    exchange: KrxExchangeConfig
    market: DailyMarketBinding
    execution_timing: ExecutionTiming = "next_session_close"
    session_closes: tuple[datetime, ...] = Field(min_length=1)
    session_opens: tuple[datetime, ...] = ()
    constraint_policy: MvpConstraintPolicy | None = None

    @model_validator(mode="after")
    def validate_frozen_execution(self) -> "FrozenDailyExecutionSpec":
        if len(self.parent_decision_artifact_ids) != len(
            set(self.parent_decision_artifact_ids)
        ):
            raise ValueError("parent decision artifact IDs must be unique")
        _validate_environment(
            account=self.account,
            instruments=self.instruments,
            exchange=self.exchange,
        )
        _validate_schedule(
            session_closes=self.session_closes,
            session_opens=self.session_opens,
            execution_timing=self.execution_timing,
        )
        return self

    def frozen_config_fingerprint(self) -> str:
        payload = _base_config_payload(
            account=self.account,
            instruments=self.instruments,
            exchange=self.exchange,
            market=self.market,
            execution_timing=self.execution_timing,
            constraint_policy=self.constraint_policy,
        )
        payload["parent_decision_artifact_ids"] = list(
            self.parent_decision_artifact_ids
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
