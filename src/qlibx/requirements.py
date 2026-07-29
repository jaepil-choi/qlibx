"""Public capability requirement declarations and pure satisfaction evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RequirementStatus = Literal["satisfied", "unsatisfied", "not_requested"]


@dataclass(frozen=True, slots=True)
class DerivationAlternative:
    alternative_id: str
    description: str
    required_inputs: tuple[str, ...]
    derivation: str


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    requirement_id: str
    role: str
    meaning: str
    axis: str
    unit: str
    currency: str
    purpose: str
    satisfaction_rule: str
    availability: str
    mandatory: bool
    unavailable_effect: str
    alternatives: tuple[DerivationAlternative, ...]
    next_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityRequirements:
    capability_id: str
    capability_version: str
    summary: str
    requirements: tuple[CapabilityRequirement, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    requirement_id: str
    alternative_id: str
    satisfied: bool
    reason: str
    source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AlternativeResolution:
    alternative_id: str
    satisfied: bool
    reason: str
    source: str | None
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RequirementResult:
    requirement_id: str
    role: str
    status: RequirementStatus
    reason: str
    selected_alternative: str | None
    alternatives: tuple[AlternativeResolution, ...]


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    capability_id: str
    capability_version: str
    results: tuple[RequirementResult, ...]
    ready: bool
    satisfied_requirements: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    next_commands: tuple[str, ...]
    retryable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": {
                "id": self.capability_id,
                "version": self.capability_version,
            },
            "requirements": [asdict(item) for item in self.results],
            "satisfied_requirements": list(self.satisfied_requirements),
            "missing_requirements": list(self.missing_requirements),
            "next_commands": list(self.next_commands),
            "retryable": self.retryable,
            "ready": self.ready,
        }


@dataclass(frozen=True, slots=True)
class CapabilityPlan:
    declaration: CapabilityRequirements
    resolution: CapabilityResolution
    parameters: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()
    ready: bool = field(init=False)
    read_only: bool = True
    mutates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ready", self.resolution.ready)


@dataclass(frozen=True, slots=True)
class UnavailableOutput:
    output_id: str
    requirement_ids: tuple[str, ...]
    reason: str


def evaluate_requirements(
    declaration: CapabilityRequirements,
    evidence: tuple[RequirementEvidence, ...] = (),
    *,
    requested_optional: tuple[str, ...] = (),
) -> CapabilityResolution:
    """Evaluate one declaration without project, catalog, CLI, or error dependencies."""
    declared_ids = {item.requirement_id for item in declaration.requirements}
    if len(declared_ids) != len(declaration.requirements):
        raise ValueError("capability declaration has duplicate requirement IDs")
    declared_alternatives = {
        (requirement.requirement_id, alternative.alternative_id)
        for requirement in declaration.requirements
        for alternative in requirement.alternatives
    }
    if any(not requirement.alternatives for requirement in declaration.requirements):
        raise ValueError("every capability requirement must declare an alternative")
    requested = set(requested_optional)
    unknown_requested = sorted(requested - declared_ids)
    if unknown_requested:
        raise ValueError(f"unknown optional requirements requested: {unknown_requested}")
    evidence_keys = [(item.requirement_id, item.alternative_id) for item in evidence]
    if len(set(evidence_keys)) != len(evidence_keys):
        raise ValueError("requirement evidence contains duplicate alternative entries")
    unknown_evidence = sorted(set(evidence_keys) - declared_alternatives)
    if unknown_evidence:
        raise ValueError(f"requirement evidence is not declared: {unknown_evidence}")
    evidence_by_key = dict(zip(evidence_keys, evidence, strict=True))
    results: list[RequirementResult] = []
    missing: list[str] = []
    satisfied: list[str] = []
    commands: list[str] = []
    for requirement in declaration.requirements:
        active = requirement.mandatory or requirement.requirement_id in requested
        if not active:
            results.append(
                RequirementResult(
                    requirement.requirement_id,
                    requirement.role,
                    "not_requested",
                    "Optional requirement was not requested.",
                    None,
                    (),
                )
            )
            continue
        alternatives: list[AlternativeResolution] = []
        for alternative in requirement.alternatives:
            observed = evidence_by_key.get((requirement.requirement_id, alternative.alternative_id))
            alternatives.append(
                AlternativeResolution(
                    alternative.alternative_id,
                    observed.satisfied if observed is not None else False,
                    (
                        observed.reason
                        if observed is not None
                        else "No evidence was provided for this alternative."
                    ),
                    observed.source if observed is not None else None,
                    dict(observed.details) if observed is not None else {},
                )
            )
        selected = next((item for item in alternatives if item.satisfied), None)
        if selected is not None:
            satisfied.append(requirement.requirement_id)
            results.append(
                RequirementResult(
                    requirement.requirement_id,
                    requirement.role,
                    "satisfied",
                    selected.reason,
                    selected.alternative_id,
                    tuple(alternatives),
                )
            )
            continue
        missing.append(requirement.requirement_id)
        reasons = tuple(item.reason for item in alternatives)
        reason = "; ".join(dict.fromkeys(reasons)) or requirement.unavailable_effect
        commands.extend(requirement.next_commands)
        results.append(
            RequirementResult(
                requirement.requirement_id,
                requirement.role,
                "unsatisfied",
                reason,
                None,
                tuple(alternatives),
            )
        )
    unique_commands = tuple(dict.fromkeys(commands))
    return CapabilityResolution(
        capability_id=declaration.capability_id,
        capability_version=declaration.capability_version,
        results=tuple(results),
        ready=not missing,
        satisfied_requirements=tuple(sorted(satisfied)),
        missing_requirements=tuple(sorted(missing)),
        next_commands=unique_commands,
        retryable=bool(unique_commands),
    )


def make_plan(
    declaration: CapabilityRequirements,
    resolution: CapabilityResolution,
    *,
    parameters: dict[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
    unsupported_features: tuple[str, ...] = (),
) -> CapabilityPlan:
    return CapabilityPlan(
        declaration=declaration,
        resolution=resolution,
        parameters=dict(parameters or {}),
        warnings=warnings,
        unsupported_features=unsupported_features,
    )


__all__ = [
    "AlternativeResolution",
    "CapabilityPlan",
    "CapabilityRequirement",
    "CapabilityRequirements",
    "CapabilityResolution",
    "DerivationAlternative",
    "RequirementEvidence",
    "RequirementResult",
    "RequirementStatus",
    "UnavailableOutput",
    "evaluate_requirements",
    "make_plan",
]
