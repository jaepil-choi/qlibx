import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from strategy import SampleSignedConstraintStrategy

from qlibx import (
    ConstraintAdjustmentSpec,
    ConstraintValidationSpec,
    ConstructionProfile,
    ExecutionLotInput,
    MvpConstraintPolicy,
    OutcomeStatus,
    PortfolioConstructionRequest,
    QlibxProject,
    StrategyInvocation,
)
from qlibx.data import DatasetRegistration

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
    if project.registry_snapshot().get("sample-k200-benchmark") is None:
        require_complete(
            project.register_dataset(
                DatasetRegistration.model_validate_json(
                    json.dumps(registration_payload, ensure_ascii=False)
                )
            ),
            "sample benchmark registration",
        )

    evaluation_time = datetime(2024, 1, 3, 15, 30, tzinfo=KST)
    strategy = require_complete(
        project.invoke(
            SampleSignedConstraintStrategy(),
            StrategyInvocation(
                invocation_id="sample-constraint-signed",
                evaluation_time=evaluation_time,
                config_fingerprint="sample-constraint-signed-v1",
            ),
        ),
        "signed Strategy",
    )
    portfolio = require_complete(
        project.construct_portfolio(
            PortfolioConstructionRequest(
                invocation_id="sample-constraint-portfolio",
                source_artifact_id=strategy.result.artifact.artifact_id,
                evaluation_time=evaluation_time,
                config_fingerprint="sample-constraint-portfolio-v1",
                profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
                requested_budget=1.0,
            )
        ),
        "signed portfolio construction",
    )

    with (sample_dir / "lots.csv").open(encoding="utf-8", newline="") as handle:
        lot_rows = tuple(csv.DictReader(handle))
    policy = MvpConstraintPolicy(
        policy_id="sample-mvp-no-short-cap-v1",
        benchmark_dataset_id="sample-k200-benchmark",
    )
    adjustment = require_complete(
        project.adjust_constraints(
            ConstraintAdjustmentSpec(
                invocation_id="sample-constraint-adjustment",
                source_portfolio_artifact_id=portfolio.diagnostics[0].artifact_id,
                evaluation_time=evaluation_time,
                policy=policy,
                account_state_identity="sample-account:v0",
                capital=970_000,
                lots=tuple(
                    ExecutionLotInput(
                        instrument=row["ticker"],
                        price=float(row["price"]),
                        lot_size=float(row["lot_size"]),
                        current_quantity=float(row["current_quantity"]),
                    )
                    for row in lot_rows
                ),
            )
        ),
        "constraint adjustment",
    )
    validation = require_complete(
        project.validate_constraints(
            ConstraintValidationSpec(
                invocation_id="sample-constraint-validation",
                adjustment_artifact_id=adjustment.diagnostics[0].artifact_id,
                evaluation_time=evaluation_time,
                policy=policy,
            )
        ),
        "independent constraint validation",
    )

    return {
        "original_weights": {
            item.instrument: item.weight for item in adjustment.result.original_weights
        },
        "adjusted_weights": {
            item.instrument: item.weight for item in adjustment.result.adjusted_weights
        },
        "adjustment_items": [
            {
                "instrument": item.instrument,
                "benchmark_weight": item.benchmark_weight,
                "cap": item.cap,
                "adjusted_weight": item.adjusted_weight,
                "unresolved_excess": item.unresolved_excess,
                "reasons": list(item.reasons),
            }
            for item in adjustment.result.items
        ],
        "cash_residual": adjustment.result.cash_residual,
        "unresolved_excess": adjustment.result.unresolved_excess,
        "compliant": validation.result.compliant,
        "failed_findings": [
            {
                "instrument": item.instrument,
                "metric": item.metric,
                "measured": item.measured,
                "bound": item.bound,
                "excess": item.excess,
            }
            for item in validation.result.findings
            if not item.passed
        ],
        "adjustment_dataset_ids": [
            access.dataset_id for access in adjustment.result.accesses
        ],
        "validation_dataset_ids": [
            access.dataset_id for access in validation.result.accesses
        ],
        "artifact_types": sorted(
            {envelope.artifact_type for envelope in project.artifacts.list_envelopes()}
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))
