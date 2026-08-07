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


class DailySimulationSpec(QlibxModel):
    """Frozen public input for the supported next-session-close simulation."""

    spec_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    strategy_fingerprint: str = Field(min_length=1)
    account: DailyAccountSeed
    instruments: tuple[ExecutableInstrument, ...] = Field(min_length=1)
    exchange: KrxExchangeConfig
    market: DailyMarketBinding
    decision_times: tuple[datetime, ...]
    session_closes: tuple[datetime, ...] = Field(min_length=1)
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = ()

    @model_validator(mode="after")
    def validate_current_daily_scope(self) -> "DailySimulationSpec":
        instrument_ids = tuple(item.instrument_id for item in self.instruments)
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("daily simulation instruments must be unique")
        if any(item.exchange_id != self.exchange.exchange_id for item in self.instruments):
            raise ValueError("instrument exchange_id must match the daily exchange")
        if any(item.currency != self.account.base_currency for item in self.instruments):
            raise ValueError("instrument currency must match the Account base currency")
        if self.exchange.participation_rate is not None:
            raise ValueError("public daily simulation does not support volume participation")
        if self.exchange.impact_rate != 0:
            raise ValueError("public daily simulation does not support market impact")
        binding_roles = [binding.consumer_role for binding in self.artifact_bindings]
        if len(binding_roles) != len(set(binding_roles)):
            raise ValueError("daily Strategy artifact binding roles must be unique")

        decisions = tuple(require_aware(value) for value in self.decision_times)
        sessions = tuple(require_aware(value) for value in self.session_closes)
        if decisions != tuple(sorted(set(decisions))):
            raise ValueError("decision_times must be unique and sorted")
        if sessions != tuple(sorted(set(sessions))):
            raise ValueError("session_closes must be unique and sorted")
        return self

    def frozen_config_fingerprint(self) -> str:
        """Hash economic configuration separately from run schedule and run identity."""

        payload = {
            "spec_schema_version": self.spec_schema_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "account": self.account.model_dump(mode="json"),
            "instruments": [item.model_dump(mode="json") for item in self.instruments],
            "exchange": self.exchange.model_dump(mode="json"),
            "market": self.market.model_dump(mode="json"),
        }
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