"""Data discovery, registration, profiles, and config-driven loading."""

from qlibx.catalog import ConfigDrivenDataLoader, DataCatalog, DatasetSpec, SourceSpec
from qlibx.discovery import DataCandidate, DataInspection, discover_data, inspect_data
from qlibx.profiles import (
    ExecutionProfilePlan,
    execution_profile_requirements,
    plan_execution_profile,
)
from qlibx.registration import (
    RegistrationPlan,
    RegistrationResult,
    data_requirements,
    plan_registration,
    register_dataset,
)

__all__ = [
    "ConfigDrivenDataLoader",
    "DataCandidate",
    "DataCatalog",
    "DataInspection",
    "DatasetSpec",
    "ExecutionProfilePlan",
    "RegistrationPlan",
    "RegistrationResult",
    "SourceSpec",
    "data_requirements",
    "discover_data",
    "execution_profile_requirements",
    "inspect_data",
    "plan_execution_profile",
    "plan_registration",
    "register_dataset",
]
