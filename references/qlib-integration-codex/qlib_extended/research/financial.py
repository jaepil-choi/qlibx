from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from qlib_extended.research.alpha import AlphaDefinition
from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.evaluation import (
    WalkForwardScheme,
    evaluate_walk_forward_returns,
)
from qlib_extended.research.manifest import MemberWeight, RunSpec
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class FinancialShadowSummary:
    atomic_runs: int
    family_runs: int
    deprecated_252d_candidates: int
    registered_run_ids: tuple[str, ...]


def publish_financial_shadow_outputs(
    financial_root: Path,
    *,
    definition: AlphaDefinition,
    scheme: WalkForwardScheme,
    store: ImmutableArtifactStore,
    catalog: AlphaPoolCatalog,
) -> FinancialShadowSummary:
    if definition.family != "financial" or definition.track != "financial_shadow":
        raise ValueError("Financial publication requires a financial_shadow definition.")
    root = financial_root.resolve()
    selected = _read_json(root / "selected_candidates.json")
    ensemble_payload = _read_json(root / "family_ensembles.json")
    candidates = _require_list(selected.get("candidates"), "selected candidates")
    ensembles = _require_list(ensemble_payload, "family ensembles")
    quarterly = [item for item in candidates if int(item["frequency_days"]) == 63]
    deprecated = [item for item in candidates if int(item["frequency_days"]) > 63]
    quarterly_ensembles = [
        item for item in ensembles if int(item["frequency_days"]) == 63
    ]
    if len(quarterly_ensembles) != 1:
        raise ValueError("Expected exactly one 63-day financial family ensemble.")

    returns = pd.read_parquet(root / "results" / "selected_daily_returns.parquet")
    if "date" not in returns.columns:
        raise KeyError("Financial daily return artifact is missing date.")
    returns = returns.set_index(pd.to_datetime(returns.pop("date"))).sort_index()
    source_manifest = _read_json(root / "results" / "run_manifest.json")
    created_at = str(source_manifest["run_time_utc"])
    data_fingerprint = _hash_payload(source_manifest["source_manifest"])

    manifests: list[Path] = []
    member_specs: dict[str, RunSpec] = {}
    for attempt, candidate in enumerate(quarterly):
        name = str(candidate["name"])
        gross_column = f"{name}_gross"
        if gross_column not in returns:
            raise KeyError(f"Missing selected return column: {gross_column}")
        spec = RunSpec(
            alpha_key=f"{definition.key}.{name}",
            family="financial",
            run_kind="atomic",
            research_track="financial_shadow",
            order_calendar_key=str(candidate["order_calendar_key"]),
            rebalance_days=int(candidate["frequency_days"]),
            status="complete",
            config_hash=_hash_payload(
                {"definition_hash": definition.config_hash, "candidate": candidate}
            ),
            data_fingerprint=data_fingerprint,
            attempt=attempt,
            created_at=created_at,
        )
        member_specs[name] = spec
        daily = returns[gross_column].fillna(0.0).astype("float64")
        weights = pd.read_parquet(root / str(candidate["path"]))
        run_dir = store.publish(
            spec,
            metrics=evaluate_walk_forward_returns(
                daily, scheme, metric_prefix="gross_excess"
            ),
            frames={
                "daily_returns": daily.to_frame("gross_excess_return"),
                "target_weights": weights,
            },
            provenance=_provenance(
                definition,
                candidate,
                source_manifest,
                classification="quarterly financial proxy; shadow only",
            ),
        )
        manifests.append(run_dir / "manifest.json")

    ensemble = quarterly_ensembles[0]
    member_names = [str(name) for name in ensemble["members"]]
    if set(member_names) != set(member_specs):
        raise ValueError("63-day family members do not match published atomic candidates.")
    family_name = str(ensemble["name"])
    net_column = f"{family_name}_net"
    if net_column not in returns:
        raise KeyError(f"Missing family net return column: {net_column}")
    family_spec = RunSpec(
        alpha_key=f"{definition.key}.{family_name}",
        family="financial",
        run_kind="family",
        research_track="financial_shadow",
        order_calendar_key=str(ensemble["order_calendar_key"]),
        rebalance_days=int(ensemble["frequency_days"]),
        status="complete",
        config_hash=_hash_payload(
            {"definition_hash": definition.config_hash, "ensemble": ensemble}
        ),
        data_fingerprint=data_fingerprint,
        created_at=created_at,
    )
    daily_net = returns[net_column].fillna(0.0).astype("float64")
    family_dir = store.publish(
        family_spec,
        metrics=evaluate_walk_forward_returns(
            daily_net, scheme, metric_prefix="net_excess"
        ),
        members=[
            MemberWeight(member_specs[name].run_id, float(ensemble["member_weight"]))
            for name in member_names
        ],
        frames={
            "daily_returns": daily_net.to_frame("net_excess_return"),
            "target_weights": pd.read_parquet(root / str(ensemble["path"])),
        },
        provenance=_provenance(
            definition,
            ensemble,
            source_manifest,
            classification="same-calendar quarterly financial family; shadow only",
        ),
    )
    manifests.append(family_dir / "manifest.json")
    run_ids = tuple(catalog.register_manifests(manifests))
    return FinancialShadowSummary(
        atomic_runs=len(quarterly),
        family_runs=1,
        deprecated_252d_candidates=len(deprecated),
        registered_run_ids=run_ids,
    )


def _provenance(
    definition: AlphaDefinition,
    resolved: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    *,
    classification: str,
) -> dict[str, Any]:
    return {
        "alpha_definition": definition.path.as_posix(),
        "alpha_definition_hash": definition.config_hash,
        "classification": classification,
        "pit_limitation": source_manifest["availability_contract"]["warning"],
        "selection_audit": (
            "Existing fixed-split selected output re-evaluated on annual walk-forward "
            "segments; it is not a newly frozen or true-forward result."
        ),
        "resolved_config": dict(resolved),
        "source_run_time_utc": source_manifest["run_time_utc"],
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of mappings.")
    return value


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
