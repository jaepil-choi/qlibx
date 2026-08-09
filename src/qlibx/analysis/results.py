"""Portable analysis values and presentation-only report models."""

import hashlib
import json
import math
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from qlibx.context import AccessRecord, StateAccessRecord
from qlibx.data import ComponentRequirement
from qlibx.models import QlibxModel


class RendererKind(StrEnum):
    TABLE = "table"
    CHART = "chart"
    MACHINE = "machine"


class AnalysisMetric(QlibxModel):
    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)


class AnalysisRecord(QlibxModel):
    record_type: Literal["constraint_finding", "missing_input"]
    identity: str = Field(min_length=1)
    metric: str | None = None
    measured: float | None = None
    bound: float | None = None
    excess: float | None = Field(default=None, ge=0)
    passed: bool | None = None
    error_code: str | None = None
    state_identity: str | None = None


class AnalysisValues(QlibxModel):
    metrics: tuple[AnalysisMetric, ...]
    records: tuple[AnalysisRecord, ...]


class AnalysisResult(QlibxModel):
    analysis_schema_version: int = 1
    invocation_id: str
    analysis_kind: Literal["simulation", "monitoring", "signal"]
    evaluation_time: datetime
    metrics: tuple[AnalysisMetric, ...]
    records: tuple[AnalysisRecord, ...] = ()
    source_artifact_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    state_semantics: Literal["actual_account", "not_applicable"]
    values_fingerprint: str
    accesses: tuple[AccessRecord, ...] = ()


class ReportResult(QlibxModel):
    report_schema_version: int = 1
    invocation_id: str
    renderer: RendererKind
    source_analysis_artifact_id: str
    values_fingerprint: str
    metrics: tuple[AnalysisMetric, ...]
    records: tuple[AnalysisRecord, ...]
    rendered_content: str


class SimulationAnalysisRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    checkpoint_artifact_id: str = Field(min_length=1)
    execution_artifact_ids: tuple[str, ...]
    failure_artifact_ids: tuple[str, ...] = ()
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)


class MonitoringAnalysisRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    monitoring_artifact_ids: tuple[str, ...]
    missing_input_artifact_ids: tuple[str, ...] = ()
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)


class SignalAnalysisRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    signal_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    return_session: date
    return_session_timezone: str = Field(min_length=1)
    return_requirement: ComponentRequirement
    config_fingerprint: str = Field(min_length=1)
    resolves_error_artifact_id: str | None = None

    @field_validator("return_session_timezone")
    @classmethod
    def validate_return_session_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown return_session_timezone: {value!r}") from exc
        return value


class ReportRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    analysis_artifact_id: str = Field(min_length=1)
    renderer: RendererKind
    config_fingerprint: str = Field(min_length=1)


class ExecutionAnalysisInput(QlibxModel):
    event_id: str
    event_time: datetime
    account_id: str
    total_cost: float = Field(ge=0)
    fill_count: int = Field(ge=0)
    limitations: tuple[str, ...]


class SimulationAnalysisInput(QlibxModel):
    initial_account: StateAccessRecord
    checkpoint_state: StateAccessRecord
    journal_event_count: int = Field(ge=0)
    journal_has_fills: bool = False
    executions: tuple[ExecutionAnalysisInput, ...]
    failure_count: int = Field(ge=0)


class MonitoringFindingInput(QlibxModel):
    state_identity: str
    instrument: str
    metric: str
    measured: float
    bound: float
    excess: float = Field(ge=0)
    passed: bool


class MonitoringAnalysisInput(QlibxModel):
    findings: tuple[MonitoringFindingInput, ...]
    missing_error_codes: tuple[str, ...]


class SignalValue(QlibxModel):
    instrument: str = Field(min_length=1)
    value: float


class SignalAnalysisInput(QlibxModel):
    signal_semantics: str = Field(min_length=1)
    signal_observation_time: datetime
    signals: tuple[SignalValue, ...]
    returns: tuple[SignalValue, ...]
    accesses: tuple[AccessRecord, ...]


class AnalysisError(ValueError):
    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


def values_fingerprint(
    metrics: tuple[AnalysisMetric, ...],
    records: tuple[AnalysisRecord, ...],
) -> str:
    payload = AnalysisValues(metrics=metrics, records=records).model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def analyze_simulation(
    request: SimulationAnalysisRequest,
    source: SimulationAnalysisInput,
) -> AnalysisResult:
    if not source.executions and source.journal_has_fills:
        raise AnalysisError("ANALYSIS_EXECUTION_INPUT_MISSING", {})
    account_ids = {item.account_id for item in source.executions}
    account_ids.add(source.checkpoint_state.account_id)
    if len(account_ids) != 1:
        raise AnalysisError(
            "ANALYSIS_ACCOUNT_ID_MISMATCH",
            {"account_ids": sorted(account_ids)},
        )
    account_ids.add(source.initial_account.account_id)
    initial_nav = source.initial_account.nav
    if initial_nav <= 0:
        raise AnalysisError(
            "ANALYSIS_INITIAL_NAV_NON_POSITIVE",
            {"initial_nav": initial_nav},
        )
    if source.checkpoint_state.valuation_status != "COMPLETE":
        raise AnalysisError(
            "ANALYSIS_FINAL_VALUATION_INCOMPLETE",
            {"valuation_status": source.checkpoint_state.valuation_status},
        )
    marked_values: list[float] = []
    for holding in source.checkpoint_state.holdings:
        if holding.mark is None:
            raise AnalysisError(
                "ANALYSIS_FINAL_VALUATION_INCOMPLETE",
                {"instrument": holding.instrument_id},
            )
        marked_values.append(holding.quantity * holding.mark)
    final_nav = source.checkpoint_state.nav
    gross = sum(abs(value) for value in marked_values) / final_nav if final_nav else 0.0
    net = sum(marked_values) / final_nav if final_nav else 0.0
    metrics = (
        AnalysisMetric(
            name="total_return",
            value=final_nav / initial_nav - 1,
            unit="fraction",
        ),
        AnalysisMetric(
            name="total_cost",
            value=sum(item.total_cost for item in source.executions),
            unit="account_currency",
        ),
        AnalysisMetric(name="gross_exposure", value=gross, unit="fraction"),
        AnalysisMetric(name="net_exposure", value=net, unit="fraction"),
        AnalysisMetric(
            name="fill_count",
            value=float(sum(item.fill_count for item in source.executions)),
            unit="count",
        ),
        AnalysisMetric(
            name="failure_count",
            value=float(source.failure_count),
            unit="count",
        ),
        AnalysisMetric(
            name="journal_event_count",
            value=float(source.journal_event_count),
            unit="count",
        ),
    )
    ordered_executions = tuple(
        sorted(source.executions, key=lambda item: (item.event_time, item.event_id))
    )
    limitations = tuple(
        dict.fromkeys(
            limitation
            for execution in ordered_executions
            for limitation in execution.limitations
        )
    )
    return AnalysisResult(
        invocation_id=request.invocation_id,
        analysis_kind="simulation",
        evaluation_time=request.evaluation_time,
        metrics=metrics,
        source_artifact_ids=(
            request.checkpoint_artifact_id,
            *sorted(request.execution_artifact_ids),
            *sorted(request.failure_artifact_ids),
        ),
        limitations=limitations,
        state_semantics="actual_account",
        values_fingerprint=values_fingerprint(metrics, ()),
    )


def analyze_monitoring(
    request: MonitoringAnalysisRequest,
    source: MonitoringAnalysisInput,
) -> AnalysisResult:
    records = tuple(
        AnalysisRecord(
            record_type="constraint_finding",
            identity=f"{item.state_identity}:{item.instrument}:{item.metric}",
            metric=item.metric,
            measured=item.measured,
            bound=item.bound,
            excess=item.excess,
            passed=item.passed,
            state_identity=item.state_identity,
        )
        for item in source.findings
    ) + tuple(
        AnalysisRecord(
            record_type="missing_input",
            identity=f"missing:{index}:{code}",
            error_code=code,
        )
        for index, code in enumerate(source.missing_error_codes)
    )
    metrics = (
        AnalysisMetric(
            name="evaluated_finding_count",
            value=float(len(source.findings)),
            unit="count",
        ),
        AnalysisMetric(
            name="breach_count",
            value=float(sum(not item.passed for item in source.findings)),
            unit="count",
        ),
        AnalysisMetric(
            name="missing_input_count",
            value=float(len(source.missing_error_codes)),
            unit="count",
        ),
    )
    return AnalysisResult(
        invocation_id=request.invocation_id,
        analysis_kind="monitoring",
        evaluation_time=request.evaluation_time,
        metrics=metrics,
        records=records,
        source_artifact_ids=(
            *request.monitoring_artifact_ids,
            *request.missing_input_artifact_ids,
        ),
        state_semantics="actual_account",
        values_fingerprint=values_fingerprint(metrics, records),
    )


def analyze_signal(
    request: SignalAnalysisRequest,
    source: SignalAnalysisInput,
) -> AnalysisResult:
    signals = {item.instrument: item.value for item in source.signals}
    returns = {item.instrument: item.value for item in source.returns}
    if len(signals) != len(source.signals) or len(returns) != len(source.returns):
        raise AnalysisError("ANALYSIS_SIGNAL_AXIS_DUPLICATE", {})
    if signals.keys() != returns.keys() or len(signals) < 2:
        raise AnalysisError(
            "ANALYSIS_SIGNAL_RETURN_COVERAGE_INVALID",
            {
                "signal_instruments": sorted(signals),
                "return_instruments": sorted(returns),
            },
        )
    instruments = sorted(signals)
    signal_values = [signals[instrument] for instrument in instruments]
    return_values = [returns[instrument] for instrument in instruments]
    if not all(math.isfinite(value) for value in (*signal_values, *return_values)):
        raise AnalysisError("ANALYSIS_SIGNAL_VALUE_NON_FINITE", {})

    signal_mean = sum(signal_values) / len(signal_values)
    return_mean = sum(return_values) / len(return_values)
    centered_signal = [value - signal_mean for value in signal_values]
    centered_return = [value - return_mean for value in return_values]
    signal_ss = sum(value * value for value in centered_signal)
    return_ss = sum(value * value for value in centered_return)
    if signal_ss <= 0 or return_ss <= 0:
        raise AnalysisError(
            "ANALYSIS_SIGNAL_VARIANCE_MISSING",
            {"signal_sum_squares": signal_ss, "return_sum_squares": return_ss},
        )
    information_coefficient = sum(
        signal * realized
        for signal, realized in zip(centered_signal, centered_return, strict=True)
    ) / math.sqrt(signal_ss * return_ss)
    gross = sum(abs(value) for value in centered_signal)
    hypothetical_return = sum(
        signal / gross * realized
        for signal, realized in zip(centered_signal, return_values, strict=True)
    )
    metrics = (
        AnalysisMetric(name="signal_count", value=float(len(instruments)), unit="count"),
        AnalysisMetric(
            name="information_coefficient",
            value=information_coefficient,
            unit="correlation",
        ),
        AnalysisMetric(
            name="hypothetical_long_short_return",
            value=hypothetical_return,
            unit="fraction",
        ),
    )
    return AnalysisResult(
        invocation_id=request.invocation_id,
        analysis_kind="signal",
        evaluation_time=request.evaluation_time,
        metrics=metrics,
        source_artifact_ids=(request.signal_artifact_id,),
        limitations=(
            "hypothetical zero-cost weights are demeaned signal values normalized to unit gross",
            "result is research analysis and does not create an executable portfolio or Account",
        ),
        state_semantics="not_applicable",
        values_fingerprint=values_fingerprint(metrics, ()),
        accesses=source.accesses,
    )
def render_analysis(
    request: ReportRequest,
    analysis: AnalysisResult,
) -> ReportResult:
    if request.renderer is RendererKind.TABLE:
        metric_lines = [
            f"{item.name}\t{item.value:.12g}\t{item.unit}"
            for item in analysis.metrics
        ]
        record_lines = [
            (
                f"{item.record_type}\t{item.identity}\t"
                f"{item.error_code or item.metric or ''}"
            )
            for item in analysis.records
        ]
        content = "\n".join(("name\tvalue\tunit", *metric_lines, *record_lines))
    elif request.renderer is RendererKind.CHART:
        content = json.dumps(
            {
                "series": [
                    {"name": item.name, "value": item.value, "unit": item.unit}
                    for item in analysis.metrics
                ],
                "records": [item.model_dump(mode="json") for item in analysis.records],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        content = analysis.model_dump_json()
    return ReportResult(
        invocation_id=request.invocation_id,
        renderer=request.renderer,
        source_analysis_artifact_id=request.analysis_artifact_id,
        values_fingerprint=analysis.values_fingerprint,
        metrics=analysis.metrics,
        records=analysis.records,
        rendered_content=content,
    )
