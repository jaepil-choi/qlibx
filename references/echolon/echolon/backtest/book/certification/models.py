"""Frozen schemas for the packaged futures book certification fixture."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import warnings
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echolon.panel.models import InstrumentMeta

from ..schedule import ExecutionContractSchedule


warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


FIXTURE_SCHEMA = "futures-book-certification-fixture/v1"
ORACLE_SCHEMA = "futures-book-certification-oracle/v1"


def canonical_artifact_sha256(value: BaseModel | dict[str, Any]) -> str:
    """Hash canonical JSON after excluding only the top-level digest."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("sha256", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FixtureBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    date: dt.date
    contract: str
    open: float
    settle: float
    suspended: bool = False


class FixtureInstrumentMeta(InstrumentMeta):
    """Frozen explicit metadata used by a certification scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FixtureInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    instrument: str
    meta: FixtureInstrumentMeta
    main_bars: tuple[FixtureBar, ...]
    exact_bars: tuple[FixtureBar, ...]

    @model_validator(mode="after")
    def _validate_identity(self) -> "FixtureInstrument":
        if self.instrument != self.instrument.strip().lower() or not self.instrument:
            raise ValueError("fixture instrument must be normalized lowercase text")
        if self.meta.instrument_id != self.instrument:
            raise ValueError("fixture metadata identity does not match its instrument")
        if not self.main_bars or not self.exact_bars:
            raise ValueError("fixture instruments require main and exact bars")
        main_dates = tuple(bar.date for bar in self.main_bars)
        if tuple(sorted(set(main_dates))) != main_dates:
            raise ValueError("main bars must have unique, ordered dates")
        identities = tuple((bar.date, bar.contract) for bar in self.exact_bars)
        if len(set(identities)) != len(identities):
            raise ValueError("exact fixture bars cannot repeat date-contract identities")
        if tuple(sorted(identities)) != identities:
            raise ValueError("exact fixture bars must be deterministically ordered")
        return self


class FixtureScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: Literal["normal_scheduled", "delayed_liquidation", "blocked_terminal"]
    panel_snapshot: str
    panel_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calendar: tuple[dt.date, ...]
    instruments: tuple[FixtureInstrument, ...]
    initial_equity_rmb: float
    slippage_bps: float
    targets_by_date: tuple["FixtureTargets", ...]
    execution_contract_schedule: ExecutionContractSchedule | None = None

    @model_validator(mode="after")
    def _validate_scenario(self) -> "FixtureScenario":
        if len(self.calendar) < 2 or tuple(sorted(set(self.calendar))) != self.calendar:
            raise ValueError("scenario calendar must be unique, ordered, and nontrivial")
        names = tuple(row.instrument for row in self.instruments)
        if not names or len(set(names)) != len(names):
            raise ValueError("scenario instruments must be nonempty and unique")
        calendar = set(self.calendar)
        for row in self.instruments:
            if any(bar.date not in calendar for bar in (*row.main_bars, *row.exact_bars)):
                raise ValueError("fixture bar date lies outside the union calendar")
        target_dates = tuple(row.date for row in self.targets_by_date)
        if tuple(sorted(set(target_dates))) != target_dates:
            raise ValueError("target decision dates must be unique and ordered")
        if any(row.date not in calendar for row in self.targets_by_date):
            raise ValueError("target decision date lies outside the union calendar")
        if any(
            {target.instrument for target in row.targets}.difference(names)
            for row in self.targets_by_date
        ):
            raise ValueError("fixture target names must be declared instruments")
        schedule = self.execution_contract_schedule
        if schedule is not None:
            if schedule.source_panel_snapshot != self.panel_snapshot:
                raise ValueError("fixture schedule snapshot mismatch")
            if schedule.source_panel_manifest_sha256 != self.panel_manifest_sha256:
                raise ValueError("fixture schedule manifest mismatch")
            if schedule.instruments != names:
                raise ValueError("fixture schedule instrument order mismatch")
            if schedule.start != self.calendar[0] or schedule.end != self.calendar[-1]:
                raise ValueError("fixture schedule window mismatch")
        return self


class FixtureTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    instrument: str
    lots: float


class FixtureTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    date: dt.date
    targets: tuple[FixtureTarget, ...]

    @model_validator(mode="after")
    def _validate_unique_targets(self) -> "FixtureTargets":
        names = tuple(row.instrument for row in self.targets)
        if len(set(names)) != len(names):
            raise ValueError("fixture target decision cannot repeat an instrument")
        return self


class FeePrimitiveCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str
    meta: FixtureInstrumentMeta
    price: float
    lots_abs: float
    close_today: bool
    expected_commission_rmb: float


class LotPrimitiveCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    value: float
    min_order_size: float
    expected: int


class CertificationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["futures-book-certification-fixture/v1"] = FIXTURE_SCHEMA
    version: Literal["v1"] = "v1"
    scenarios: tuple[FixtureScenario, ...]
    fee_primitive_cases: tuple[FeePrimitiveCase, ...]
    lot_primitive_cases: tuple[LotPrimitiveCase, ...]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _verify_fixture(self) -> "CertificationFixture":
        if tuple(row.name for row in self.scenarios) != (
            "normal_scheduled",
            "delayed_liquidation",
            "blocked_terminal",
        ):
            raise ValueError("fixture scenarios must have the frozen v1 order")
        if canonical_artifact_sha256(self) != self.sha256:
            raise ValueError("certification fixture hash mismatch")
        return self


class OracleTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    date: dt.date
    instrument: str
    contract: str
    side: Literal["BUY", "SELL"]
    lots: float
    fill_price: float
    commission_rmb: float
    realized_pnl_rmb: float
    position_after: float


class ScenarioOracle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: Literal["normal_scheduled", "delayed_liquidation", "blocked_terminal"]
    status: Literal["VALID_COMPLETE", "LIQUIDATED_HALT", "INVALID_INCOMPLETE"]
    ending_cash_rmb: float
    ending_equity_rmb: float
    ending_margin_used_rmb: float
    fees_total_rmb: float
    slippage_total_rmb: float
    realized_pnl_rmb: float
    determinism_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_result_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trades: tuple[OracleTrade, ...]
    required_event_types: tuple[str, ...]


class CertificationOracle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["futures-book-certification-oracle/v1"] = ORACLE_SCHEMA
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    close_today_coverage: Literal["public_primitive_only"]
    scenarios: tuple[ScenarioOracle, ...]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _verify_oracle(self) -> "CertificationOracle":
        if canonical_artifact_sha256(self) != self.sha256:
            raise ValueError("certification oracle hash mismatch")
        return self


class CertificationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture: CertificationFixture
    oracle: CertificationOracle

    @model_validator(mode="after")
    def _bind_artifacts(self) -> "CertificationBundle":
        if self.oracle.fixture_sha256 != self.fixture.sha256:
            raise ValueError("certification oracle is not bound to the fixture")
        if tuple(row.name for row in self.oracle.scenarios) != tuple(
            row.name for row in self.fixture.scenarios
        ):
            raise ValueError("certification oracle scenario order does not match fixture")
        return self
