"""Public configuration for hypothetical signed AcademicExchange runs."""

import hashlib
import json
import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.execution.academic import (
    AcademicExchangeProfile,
    AcademicInstrumentListing,
)
from qlibx.kernel.clock import require_aware
from qlibx.models import QlibxModel


class AcademicRunSpec(QlibxModel):
    """Frozen input for exact signed portfolio execution."""

    spec_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    portfolio_artifact_ids: tuple[str, ...] = Field(min_length=1)
    initial_nav: float = Field(gt=0)
    base_currency: str = Field(min_length=3, max_length=3)
    listings: tuple[AcademicInstrumentListing, ...] = Field(min_length=1)
    session_closes: tuple[datetime, ...] = Field(min_length=1)
    profile: AcademicExchangeProfile = AcademicExchangeProfile()

    @model_validator(mode="after")
    def validate_frozen_run(self) -> "AcademicRunSpec":
        if not math.isfinite(self.initial_nav):
            raise ValueError("initial_nav must be finite")
        if len(self.portfolio_artifact_ids) != len(set(self.portfolio_artifact_ids)):
            raise ValueError("portfolio artifact IDs must be unique")
        instruments = tuple(item.instrument_id for item in self.listings)
        if len(instruments) != len(set(instruments)):
            raise ValueError("academic instrument listings must be unique")
        if any(item.currency != self.base_currency for item in self.listings):
            raise ValueError("academic listing currency must match base_currency")
        closes = tuple(require_aware(value) for value in self.session_closes)
        if closes != tuple(sorted(set(closes))):
            raise ValueError("session_closes must be unique and sorted")
        return self

    def frozen_config_fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"run_id"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
