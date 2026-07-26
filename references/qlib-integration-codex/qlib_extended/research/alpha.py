from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from qlib_extended.research.catalog import DataCatalog
from qlib_extended.research.config import (
    read_yaml_mapping,
    require_mapping,
    require_string,
)


ALPHA_FAMILIES = frozenset({"market", "consensus", "financial"})
ALPHA_TRACKS = frozenset({"trusted", "financial_shadow", "legacy"})


@dataclass(frozen=True)
class AlphaDefinition:
    path: Path
    key: str
    family: str
    track: str
    hypothesis: str
    inputs: dict[str, str]
    signal: dict[str, Any]
    execution: dict[str, Any]
    neutralization: dict[str, Any]
    search: dict[str, Any]
    config_hash: str

    @property
    def rebalance_days(self) -> int:
        return int(self.execution["rebalance_days"])

    @property
    def order_calendar_key(self) -> str:
        return str(self.execution["order_calendar_key"])

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        *,
        data_catalog: DataCatalog,
    ) -> AlphaDefinition:
        payload = read_yaml_mapping(path)
        if payload.get("schema_version") != 1:
            raise ValueError(f"Alpha schema_version must be 1: {path}")
        family = require_string(payload.get("family"), "family")
        track = require_string(payload.get("track"), "track")
        if family not in ALPHA_FAMILIES:
            raise ValueError(f"family must be one of {sorted(ALPHA_FAMILIES)}.")
        if track not in ALPHA_TRACKS:
            raise ValueError(f"track must be one of {sorted(ALPHA_TRACKS)}.")
        if family == "financial" and track == "trusted":
            raise ValueError("Financial alpha cannot use the trusted track without PIT data.")

        raw_inputs = require_mapping(payload.get("inputs"), "inputs")
        inputs = {
            require_string(alias, "inputs alias"): require_string(
                dataset, f"inputs.{alias}"
            )
            for alias, dataset in raw_inputs.items()
        }
        for dataset in inputs.values():
            data_catalog.require_dataset(dataset)

        execution = require_mapping(payload.get("execution"), "execution")
        require_string(
            execution.get("order_calendar_key"), "execution.order_calendar_key"
        )
        lag_days = _require_non_negative_int(execution.get("lag_days"), "lag_days")
        rebalance_days = _require_positive_int(
            execution.get("rebalance_days"), "rebalance_days"
        )
        max_holding_days = _require_positive_int(
            execution.get("max_holding_days"), "max_holding_days"
        )
        if lag_days < 1:
            raise ValueError("execution.lag_days must be at least one trading day.")
        if track in {"trusted", "financial_shadow"} and rebalance_days > 63:
            raise ValueError(f"{track} rebalance_days must not exceed 63.")
        if track in {"trusted", "financial_shadow"} and max_holding_days > 63:
            raise ValueError(f"{track} max_holding_days must not exceed 63.")

        signal = require_mapping(payload.get("signal"), "signal")
        require_string(signal.get("implementation"), "signal.implementation")
        definition = cls(
            path=path.resolve(),
            key=require_string(payload.get("key"), "key"),
            family=family,
            track=track,
            hypothesis=require_string(payload.get("hypothesis"), "hypothesis"),
            inputs=inputs,
            signal=dict(signal),
            execution=dict(execution),
            neutralization=dict(
                require_mapping(payload.get("neutralization"), "neutralization")
            ),
            search=dict(require_mapping(payload.get("search"), "search")),
            config_hash=_config_hash(payload),
        )
        return definition


def load_alpha_definitions(
    alpha_dir: Path,
    *,
    data_catalog: DataCatalog,
) -> dict[str, AlphaDefinition]:
    definitions: dict[str, AlphaDefinition] = {}
    for path in sorted(alpha_dir.glob("*.yaml")):
        definition = AlphaDefinition.from_yaml(path, data_catalog=data_catalog)
        if definition.key in definitions:
            raise ValueError(f"Duplicate alpha key: {definition.key}")
        definitions[definition.key] = definition
    if not definitions:
        raise ValueError(f"No alpha YAML definitions found: {alpha_dir}")
    return definitions


def _require_positive_int(value: object, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"execution.{key} must be a positive integer.")
    return value


def _require_non_negative_int(value: object, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"execution.{key} must be a non-negative integer.")
    return value


def _config_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()
