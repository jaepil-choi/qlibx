import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from strategy import SampleReversalStrategy

from qlibx import OutcomeStatus, QlibxProject, StrategyInvocation
from qlibx.analysis import RendererKind, ReportRequest, SignalAnalysisRequest
from qlibx.data import ComponentRequirement, DatasetRegistration
from qlibx.flow import (
    STORED_SIGNAL_CONTRACT,
    AnalysisFlow,
    CompositionFlow,
    PortfolioConstructionFlow,
    StoredSignalEntry,
    StoredSignalResult,
    StoredSignalWeighting,
)
from qlibx.portfolio import (
    ConstructionProfile,
    PortfolioConstructionRequest,
)

KST = ZoneInfo("Asia/Seoul")


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def main(project_root: Path) -> dict[str, object]:
    sample_dir = Path(__file__).resolve().parent
    project = QlibxProject.open(project_root)
    registration_payload = yaml.safe_load(
        (sample_dir / "registration.yaml").read_text(encoding="utf-8")
    )
    if project.registry_snapshot().get("sample-real-dw-market") is None:
        require_complete(
            project.register_dataset(
                DatasetRegistration.model_validate_json(
                    json.dumps(registration_payload, ensure_ascii=False)
                )
            ),
            "sample registration",
        )

    decision_time = datetime(2024, 1, 2, 15, 30, tzinfo=KST)
    direct = require_complete(
        project.invoke(
            SampleReversalStrategy(),
            StrategyInvocation(
                invocation_id="sample-direct",
                evaluation_time=decision_time,
                config_fingerprint="sample-direct-v1",
            ),
        ),
        "direct Strategy",
    )

    with (sample_dir / "market.csv").open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    signal = StoredSignalResult(
        signal_semantics="sample_real_dw_close_to_base_return",
        observation_time=decision_time,
        entries=tuple(
            StoredSignalEntry(
                instrument=row["ticker"],
                value=float(row["decision_return"]),
            )
            for row in rows
            if row["date"].startswith("2024-01-02")
        ),
    )
    stored = require_complete(
        project.artifacts.import_model_bytes(
            logical_identity="sample-stored-signal:2024-01-02",
            contract=STORED_SIGNAL_CONTRACT,
            producer_id="sample.external-signal",
            payload_bytes=signal.model_dump_json().encode(),
        ),
        "stored signal",
    )
    composition = CompositionFlow(
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
    )
    consumers = tuple(
        require_complete(
            composition.invoke_stored_signal_strategy(
                artifact_id=stored.result.artifact_id,
                strategy_id=f"sample.stored.{weighting.value}",
                weighting=weighting,
                invocation=StrategyInvocation(
                    invocation_id=f"sample-stored-{weighting.value}",
                    evaluation_time=decision_time,
                    config_fingerprint=f"sample-stored-{weighting.value}-v1",
                ),
            ),
            weighting.value,
        )
        for weighting in StoredSignalWeighting
    )
    portfolio = require_complete(
        PortfolioConstructionFlow(artifacts=project.artifacts).construct(
            PortfolioConstructionRequest(
                invocation_id="sample-long-only-construction",
                source_artifact_id=direct.result.artifact.artifact_id,
                evaluation_time=decision_time,
                config_fingerprint="sample-long-only-v1",
                profile=ConstructionProfile.EQUITY_LONG_ONLY,
                requested_budget=1.0,
            )
        ),
        "portfolio construction",
    )
    analysis_flow = AnalysisFlow(
        artifacts=project.artifacts,
        registry=project.registry_snapshot(),
    )
    analysis = require_complete(
        analysis_flow.analyze_signal(
            SignalAnalysisRequest(
                invocation_id="sample-signal-analysis",
                signal_artifact_id=stored.result.artifact_id,
                evaluation_time=datetime(2024, 1, 3, 15, 30, tzinfo=KST),
                return_session=date(2024, 1, 3),
                return_requirement=ComponentRequirement(
                    requirement_id="sample.analysis.return",
                    semantic_role="analysis_return",
                    dataset_id="sample-real-dw-market",
                ),
                config_fingerprint="sample-signal-analysis-v1",
            )
        ),
        "signal analysis",
    )
    report = require_complete(
        analysis_flow.render(
            ReportRequest(
                invocation_id="sample-machine-report",
                analysis_artifact_id=analysis.diagnostics[0].artifact_id,
                renderer=RendererKind.MACHINE,
                config_fingerprint="sample-machine-report-v1",
            )
        ),
        "machine report",
    )

    return {
        "direct_weights": {
            item.instrument: item.weight
            for item in direct.result.result.weights
        },
        "stored_consumer_count": len(consumers),
        "portfolio_weights": {
            item.instrument: item.weight
            for item in portfolio.result.target_weights
        },
        "analysis_metrics": {
            item.name: item.value
            for item in analysis.result.metrics
        },
        "report_artifact_id": report.diagnostics[0].artifact_id,
        "artifact_types": sorted(
            envelope.artifact_type
            for envelope in project.artifacts.list_envelopes()
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))
