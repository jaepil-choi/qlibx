"""Purpose-built portfolio book backtester."""
from .accounting import commission_rmb
from .engine import DailyBookBacktester
from .certification import (
    certification_bundle_sha256,
    load_certification_bundle,
    run_certification_scenario,
)
from .interface import IBookBacktester
from .models import (
    BookBacktestConfig,
    BookLifecycleContract,
    BookOutcome,
    BookResult,
    BookRuntimeManifest,
    EndingPendingIntent,
    EndingPosition,
    EquityPoint,
    Summary,
    TradeRecord,
)
from .nominal_schedule import (
    NominalCycleSchedule,
    NominalCycleScheduleRow,
    canonical_session_list_sha256,
    create_nominal_cycle_schedule,
    load_nominal_cycle_schedule,
    nominal_cycle_id,
    write_nominal_cycle_schedule,
)
from .risk_policy import RiskPolicyBinding
from .result_identity import (
    full_result_manifest_payload,
    full_result_manifest_sha256,
    verify_full_result_manifest_sha256,
)
from .schedule import (
    ExecutionContractSchedule,
    ExecutionContractScheduleRow,
    canonical_schedule_sha256,
    load_execution_contract_schedule,
    write_execution_contract_schedule,
)

__all__ = [
    "BookBacktestConfig",
    "BookLifecycleContract",
    "BookOutcome",
    "BookResult",
    "BookRuntimeManifest",
    "EndingPendingIntent",
    "EndingPosition",
    "DailyBookBacktester",
    "EquityPoint",
    "ExecutionContractSchedule",
    "ExecutionContractScheduleRow",
    "IBookBacktester",
    "NominalCycleSchedule",
    "NominalCycleScheduleRow",
    "RiskPolicyBinding",
    "Summary",
    "TradeRecord",
    "canonical_schedule_sha256",
    "certification_bundle_sha256",
    "commission_rmb",
    "load_certification_bundle",
    "run_certification_scenario",
    "canonical_session_list_sha256",
    "create_nominal_cycle_schedule",
    "load_execution_contract_schedule",
    "load_nominal_cycle_schedule",
    "nominal_cycle_id",
    "write_execution_contract_schedule",
    "write_nominal_cycle_schedule",
    "full_result_manifest_payload",
    "full_result_manifest_sha256",
    "verify_full_result_manifest_sha256",
]
