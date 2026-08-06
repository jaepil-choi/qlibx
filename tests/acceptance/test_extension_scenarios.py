from datetime import datetime

import duckdb
import pytest

from qlibx import OutcomeStatus
from qlibx.extensions import ExtensionValidationRequest
from tests.acceptance.real_dw_support import KST, RealDwProject

VALID_EXTENSION = '''from qlibx.data import ComponentRequirement
from qlibx.extensions import NeutralizationExtensionSpec, group_demean

EXTENSION_SPEC = NeutralizationExtensionSpec(
    extension_id="project.sector-demean",
    value_requirement=ComponentRequirement(
        requirement_id="project.sector-demean.value",
        semantic_role="extension_input_value",
        dataset_id="real-extension-market",
    ),
    group_requirement=ComponentRequirement(
        requirement_id="project.sector-demean.group",
        semantic_role="neutralization_group",
        dataset_id="real-extension-sector",
    ),
)

def transform(request):
    return group_demean(EXTENSION_SPEC.extension_id, request)
'''

INVALID_EXTENSION = '''from qlibx.data import ComponentRequirement
from qlibx.extensions import (
    NeutralizationExtensionSpec,
    NeutralizationResult,
    NeutralizedValue,
)

EXTENSION_SPEC = NeutralizationExtensionSpec(
    extension_id="project.sector-demean",
    value_requirement=ComponentRequirement(
        requirement_id="project.sector-demean.value",
        semantic_role="extension_input_value",
        dataset_id="real-extension-market",
    ),
    group_requirement=ComponentRequirement(
        requirement_id="project.sector-demean.group",
        semantic_role="neutralization_group",
        dataset_id="real-extension-sector",
    ),
)

def transform(request):
    return NeutralizationResult(
        extension_id=EXTENSION_SPEC.extension_id,
        values=tuple(
            NeutralizedValue(instrument=row.instrument, value=row.value)
            for row in request.rows
        ),
    )
'''


def _request(invocation_id: str, evaluation_time: datetime) -> ExtensionValidationRequest:
    return ExtensionValidationRequest(
        invocation_id=invocation_id,
        extension_id="project.sector-demean",
        module_path="sector_demean.py",
        evaluation_time=evaluation_time,
        config_fingerprint="project-sector-demean-validation-v1",
    )


def test_uc_extension_001_registers_only_after_real_pit_contract_validation(
    real_dw_extension_case: RealDwProject,
) -> None:
    module = (
        real_dw_extension_case.root
        / real_dw_extension_case.project.config.extension_dir
        / "sector_demean.py"
    )
    module.write_text(VALID_EXTENSION, encoding="utf-8", newline="\n")

    before_sector_release = real_dw_extension_case.project.validate_extension(
        _request(
            "extension-before-sector-release",
            datetime(2024, 2, 1, 8, 59, tzinfo=KST),
        )
    )
    assert before_sector_release.status is OutcomeStatus.FAILED
    assert before_sector_release.errors[0].error_code == "EXTENSION_VALIDATION_FAILED"
    assert real_dw_extension_case.project.registered_extensions() == ()

    module.write_text(INVALID_EXTENSION, encoding="utf-8", newline="\n")
    invalid_output = real_dw_extension_case.project.validate_extension(
        _request(
            "extension-invalid-output",
            datetime(2024, 2, 1, 9, 0, tzinfo=KST),
        )
    )
    assert invalid_output.status is OutcomeStatus.FAILED
    assert invalid_output.errors[0].error_code == "EXTENSION_VALIDATION_FAILED"
    assert "sum to zero" in invalid_output.errors[0].context["message"]
    assert real_dw_extension_case.project.registered_extensions() == ()

    module.write_text(VALID_EXTENSION, encoding="utf-8", newline="\n")
    validated = real_dw_extension_case.project.validate_extension(
        _request(
            "extension-valid-output",
            datetime(2024, 2, 1, 9, 0, tzinfo=KST),
        )
    )
    assert validated.status is OutcomeStatus.COMPLETE
    registration = validated.result
    registered = real_dw_extension_case.project.registered_extensions()
    assert registered == (registration,)
    assert registration.module_path == "qlibx_extensions/sector_demean.py"
    assert tuple(access.semantic_role for access in registration.accesses) == (
        "extension_input_value",
        "neutralization_group",
    )
    assert all(
        access.max_available_at is not None
        and access.max_available_at <= registration.evaluation_time
        for access in registration.accesses
    )
    group_access = next(
        access
        for access in registration.accesses
        if access.semantic_role == "neutralization_group"
    )
    assert group_access.max_available_at == datetime(2024, 2, 1, 9, 0, tzinfo=KST)

    market_path = real_dw_extension_case.root / "real-extension-market.parquet"
    rows = duckdb.sql(
        f"""
        SELECT ticker, extension_input_value
        FROM read_parquet('{market_path.as_posix()}')
        ORDER BY ticker
        """
    ).fetchall()
    mean = sum(float(value) for _, value in rows) / len(rows)
    expected = {ticker: float(value) - mean for ticker, value in rows}
    actual = {
        item.instrument: item.value
        for item in registration.validation_output.values
    }
    assert actual == pytest.approx(expected, abs=1e-15)
    assert sum(actual.values()) == pytest.approx(0.0, abs=1e-15)

    complete_extension_artifacts = tuple(
        item
        for item in real_dw_extension_case.project.artifacts.list_envelopes()
        if item.artifact_type == "extension_registration"
    )
    failure_artifacts = tuple(
        item
        for item in real_dw_extension_case.project.artifacts.list_envelopes(
            include_failure=True
        )
        if item.artifact_type == "operation_error"
    )
    assert len(complete_extension_artifacts) == 1
    assert len(failure_artifacts) == 2
