"""Public capability requirement declarations and pure satisfaction evaluation.

A capability answers four questions in order: what does it require, what does the world
currently offer, is that enough, and what should the caller do next. The first is a
``CapabilityRequirements`` declaration; the last three are ``gather_evidence``,
``evaluate_requirements`` and ``make_plan``, with ``plan_capability`` running the three
together.

A capability supplies only the part that is genuinely its own -- a probe answering
"can this alternative be satisfied right now" -- and never builds a ``RequirementEvidence``
by hand. Labelling an answer with the requirement and alternative it came from is
bookkeeping, and every copy of that bookkeeping is somewhere the vocabulary can drift.

This module has no dependencies, inside qlibx or out. That is deliberate: it keeps the
protocol usable from the pure domain packages, which are forbidden from importing anything
that could reach a project, a catalog, or the CLI.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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


@dataclass(frozen=True, slots=True)
class Finding:
    """One probe's answer about a single declared alternative.

    Deliberately carries no requirement or alternative ID. The probe is handed both, so
    making it repeat them back is bookkeeping the protocol can do without help -- and is
    exactly what let two capabilities describe the same fact in different words.
    """

    satisfied: bool
    reason: str
    source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


EvidenceProbe = Callable[[CapabilityRequirement, DerivationAlternative], "Finding | None"]


def gather_evidence(
    declaration: CapabilityRequirements,
    probe: EvidenceProbe,
) -> tuple[RequirementEvidence, ...]:
    """Ask ``probe`` about every declared alternative and label each answer.

    A probe returning ``None`` declines the alternative rather than refusing it.
    ``evaluate_requirements`` treats absent evidence as unsatisfied either way, so the
    difference is only in the reported reason -- and a capability should not have to invent
    one for a question it never asked.
    """
    evidence: list[RequirementEvidence] = []
    for requirement in declaration.requirements:
        for alternative in requirement.alternatives:
            finding = probe(requirement, alternative)
            if finding is None:
                continue
            evidence.append(
                RequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    alternative_id=alternative.alternative_id,
                    satisfied=finding.satisfied,
                    reason=finding.reason,
                    source=finding.source,
                    details=dict(finding.details),
                )
            )
    return tuple(evidence)


def supplied_roles_probe(
    supplied: Iterable[str],
    *,
    source: str = "runtime_arguments",
) -> EvidenceProbe:
    """The evidence rule for capabilities whose inputs are simply handed in by the caller.

    An alternative is satisfied when every role it names was supplied. Capabilities that
    read a project, a catalog, or a binding need their own probe; this one covers the case
    where "is it available" means nothing more than "did the caller pass it".
    """
    available = {str(item) for item in supplied}

    def probe(
        _requirement: CapabilityRequirement,
        alternative: DerivationAlternative,
    ) -> Finding:
        missing = sorted(set(alternative.required_inputs) - available)
        return Finding(
            satisfied=not missing,
            reason=(
                f"Every required input is supplied: {sorted(alternative.required_inputs)}."
                if not missing
                else f"Missing required input(s): {missing}."
            ),
            source=source,
            details={"supplied_roles": sorted(available), "missing_roles": missing},
        )

    return probe


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


def plan_capability(
    declaration: CapabilityRequirements,
    probe: EvidenceProbe,
    *,
    requested_optional: tuple[str, ...] = (),
    parameters: dict[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
    unsupported_features: tuple[str, ...] = (),
) -> CapabilityPlan:
    """Run the whole cycle: gather evidence, evaluate it, and return the read-only plan.

    Use the three steps separately only when something between them needs the resolution --
    warnings that depend on what turned out to be missing, for instance.
    """
    resolution = evaluate_requirements(
        declaration,
        gather_evidence(declaration, probe),
        requested_optional=requested_optional,
    )
    return make_plan(
        declaration,
        resolution,
        parameters=parameters,
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
    "EvidenceProbe",
    "Finding",
    "RequirementEvidence",
    "RequirementResult",
    "RequirementStatus",
    "UnavailableOutput",
    "evaluate_requirements",
    "gather_evidence",
    "make_plan",
    "plan_capability",
    "supplied_roles_probe",
]
