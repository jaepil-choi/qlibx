"""Value objects for a Strategy manifest, its binding, and its resolved inputs.

The manifest also declares what it requires, because that declaration depends on nothing
but the manifest itself: which registered data could satisfy it is a separate question,
answered as evidence in :mod:`qlibx.strategy_manifest.capability`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from qlibx.requirements import (
    CapabilityRequirement,
    CapabilityRequirements,
    DerivationAlternative,
)

PandasKind = Literal["table", "matrix"]
StrategyOutputKind = Literal["signal", "weight", "order", "payload"]


@dataclass(frozen=True, slots=True)
class StrategyImplementation:
    source: str
    callable: str


@dataclass(frozen=True, slots=True)
class StrategyField:
    name: str
    meaning: str
    dtype: str
    unit: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class PandasInputContract:
    kind: PandasKind
    index: tuple[str, ...]
    dtype: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyInput:
    role: str
    meaning: str
    pandas: PandasInputContract
    fields: tuple[StrategyField, ...] = ()
    inherited: bool = False


@dataclass(frozen=True, slots=True)
class StrategyManifest:
    strategy_id: str
    version: str
    name: str
    contract: str
    implementation: StrategyImplementation
    parameters: Mapping[str, Any]
    lookback_rows: int
    inputs: tuple[StrategyInput, ...]
    output_kind: StrategyOutputKind
    source_path: Path
    fingerprint: str

    @property
    def all_inputs(self) -> tuple[StrategyInput, ...]:
        return (base_universe_input(), *self.inputs)

    def requirements(self) -> CapabilityRequirements:
        return CapabilityRequirements(
            capability_id=f"strategy.{self.strategy_id}",
            capability_version=self.version,
            summary=f"Resolve registered pandas inputs for Strategy {self.name!r}.",
            requirements=tuple(_input_requirement(self, item) for item in self.all_inputs),
            parameters={
                "contract": self.contract,
                "lookback": {"kind": "rows", "value": self.lookback_rows},
                "output": {"kind": self.output_kind},
                "inputs": [input_document(item) for item in self.all_inputs],
            },
        )


@dataclass(frozen=True, slots=True)
class StrategyBindingInput:
    role: str
    registered_dataset: str
    fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyBinding:
    binding_id: str
    strategy_id: str
    strategy_version: str
    inputs: tuple[StrategyBindingInput, ...]
    source_path: Path
    fingerprint: str

    def by_role(self) -> dict[str, StrategyBindingInput]:
        return {item.role: item for item in self.inputs}


@dataclass(frozen=True, slots=True)
class ResolvedStrategyInputs:
    strategy_id: str
    strategy_version: str
    binding_id: str
    decision_time: pd.Timestamp
    inputs: Mapping[str, pd.DataFrame]
    effective_config_id: str


def base_universe_input() -> StrategyInput:
    """The mandatory input inherited by every qlibx pandas Strategy."""
    return StrategyInput(
        role="universe",
        meaning="Point-in-time research universe membership.",
        pandas=PandasInputContract(kind="matrix", index=("observation_time",), dtype="bool"),
        inherited=True,
    )


def input_document(item: StrategyInput) -> dict[str, Any]:
    """Project one declared input into the JSON an agent reads out of a plan."""
    return {
        "role": item.role,
        "meaning": item.meaning,
        "pandas": asdict(item.pandas),
        "fields": [asdict(declared) for declared in item.fields],
        "inherited": item.inherited,
    }


def manifest_document(manifest: StrategyManifest) -> dict[str, Any]:
    return {
        "strategy": {
            "id": manifest.strategy_id,
            "version": manifest.version,
            "name": manifest.name,
        },
        "contract": manifest.contract,
        "implementation": asdict(manifest.implementation),
        "lookback": {"kind": "rows", "value": manifest.lookback_rows},
        "inputs": [input_document(item) for item in manifest.all_inputs],
        "output": {"kind": manifest.output_kind},
        "fingerprint": manifest.fingerprint,
    }


def binding_document(binding: StrategyBinding) -> dict[str, Any]:
    return {
        "id": binding.binding_id,
        "strategy": {"id": binding.strategy_id, "version": binding.strategy_version},
        "inputs": {
            item.role: {
                "registered_dataset": item.registered_dataset,
                "fields": dict(item.fields),
            }
            for item in binding.inputs
        },
        "fingerprint": binding.fingerprint,
    }


def _input_requirement(
    manifest: StrategyManifest,
    item: StrategyInput,
) -> CapabilityRequirement:
    fields = tuple(declared.name for declared in item.fields)
    return CapabilityRequirement(
        requirement_id=f"input.{item.role}",
        role=item.role,
        meaning=item.meaning,
        axis=" x ".join(item.pandas.index),
        unit=", ".join(dict.fromkeys(declared.unit for declared in item.fields)) or "membership",
        currency="not_applicable",
        purpose=f"Supply bounded pandas input {item.role!r} to {manifest.strategy_id!r}.",
        satisfaction_rule=(
            "A project binding names a registered logical dataset and maps every canonical field."
        ),
        availability="Every observation must be available at or before the decision time.",
        mandatory=True,
        unavailable_effect=f"Strategy input {item.role!r} cannot be constructed.",
        alternatives=(
            DerivationAlternative(
                alternative_id="registered_binding",
                description="Use an explicit binding to a registered logical dataset.",
                required_inputs=(item.role, *fields),
                derivation="registered logical dataset projection",
            ),
        ),
        next_commands=(
            "qlibx strategy plan "
            f"--strategy {manifest.strategy_id} --binding <binding> --root <project>",
        ),
    )


__all__ = [
    "PandasInputContract",
    "PandasKind",
    "ResolvedStrategyInputs",
    "StrategyBinding",
    "StrategyBindingInput",
    "StrategyField",
    "StrategyImplementation",
    "StrategyInput",
    "StrategyManifest",
    "StrategyOutputKind",
    "base_universe_input",
    "binding_document",
    "input_document",
    "manifest_document",
]
