from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from qlib_extended.research.alpha import AlphaDefinition
from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.costs import AsymmetricCostContract
from qlib_extended.research.evaluation import (
    WalkForwardScheme,
    evaluate_walk_forward_returns,
)
from qlib_extended.research.loader import ConfigDrivenDataLoader
from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class MarketCohortContract:
    atomic: tuple[dict[str, Any], ...]
    families: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MarketCohortSummary:
    atomic_runs: int
    family_runs: int
    registered_run_ids: tuple[str, ...]
    family_run_ids: tuple[str, ...]


def load_market_cohort_contract(price_root: Path) -> MarketCohortContract:
    payload = json.loads(
        (price_root / "selected_candidates.json").read_text(encoding="utf-8")
    )
    atomic = _mapping_list(payload.get("candidates"), "price candidates")
    families = _mapping_list(payload.get("frequency_ensembles"), "frequency ensembles")
    atom_by_name = {str(item["name"]): item for item in atomic}
    for family in families:
        calendar = str(family["order_calendar_key"])
        if calendar == "mixed_frequency_research_only":
            raise ValueError("Mixed-frequency ensemble cannot be an execution cohort.")
        for member in family["members"]:
            if member not in atom_by_name:
                raise KeyError(f"Cohort member is not a selected atomic alpha: {member}")
            if str(atom_by_name[member]["order_calendar_key"]) != calendar:
                raise ValueError(f"Calendar mismatch in family {family['name']}: {member}")
    return MarketCohortContract(tuple(atomic), tuple(families))


def publish_market_calendar_cohorts(
    price_root: Path,
    *,
    definition: AlphaDefinition,
    loader: ConfigDrivenDataLoader,
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
    store: ImmutableArtifactStore,
    catalog: AlphaPoolCatalog,
) -> MarketCohortSummary:
    if definition.family != "market" or definition.track != "trusted":
        raise ValueError("Market cohort publication requires a trusted market definition.")
    root = price_root.resolve()
    contract = load_market_cohort_contract(root)
    returns = loader.load_matrix("adjusted_return")
    returns = returns.loc[scheme.start : scheme.end]
    run_manifest = json.loads(
        (root / "results" / "run_manifest.json").read_text(encoding="utf-8")
    )
    data_fingerprint = _hash_payload(run_manifest["inputs"])
    manifests: list[Path] = []
    atom_specs: dict[str, RunSpec] = {}

    for attempt, candidate in enumerate(contract.atomic):
        name = str(candidate["name"])
        target = _read_target(root / str(candidate["path"]), returns)
        gross, diagnostic_net, extra_metrics = _evaluate_target(
            target, returns, costs
        )
        spec = RunSpec(
            alpha_key=f"{definition.key}.{name}",
            family="market",
            run_kind="atomic",
            research_track="trusted",
            order_calendar_key=str(candidate["order_calendar_key"]),
            rebalance_days=int(candidate["frequency_days"]),
            status="complete",
            config_hash=_hash_payload(
                {"definition_hash": definition.config_hash, "candidate": candidate}
            ),
            data_fingerprint=data_fingerprint,
            attempt=attempt,
        )
        atom_specs[name] = spec
        metrics = [
            *evaluate_walk_forward_returns(
                gross, scheme, metric_prefix="gross_excess"
            ),
            *evaluate_walk_forward_returns(
                diagnostic_net, scheme, metric_prefix="diagnostic_net_excess"
            ),
            *extra_metrics,
        ]
        run_dir = store.publish(
            spec,
            metrics=metrics,
            frames={
                "daily_returns": pd.DataFrame(
                    {
                        "gross_excess_return": gross,
                        "diagnostic_net_excess_return": diagnostic_net,
                    }
                ),
                "target_weights": target,
            },
            provenance={
                "alpha_definition": definition.path.as_posix(),
                "classification": "historical prior-informed selected market alpha",
                "resolved_config": candidate,
                "true_forward_oos": False,
            },
        )
        manifests.append(run_dir / "manifest.json")

    family_ids: list[str] = []
    for family in contract.families:
        name = str(family["name"])
        target = _read_target(root / str(family["path"]), returns)
        gross, net, extra_metrics = _evaluate_target(target, returns, costs)
        spec = RunSpec(
            alpha_key=f"{definition.key}.{name}",
            family="market",
            run_kind="family",
            research_track="trusted",
            order_calendar_key=str(family["order_calendar_key"]),
            rebalance_days=int(family["frequency_days"]),
            status="complete",
            config_hash=_hash_payload(
                {"definition_hash": definition.config_hash, "family": family}
            ),
            data_fingerprint=data_fingerprint,
        )
        family_ids.append(spec.run_id)
        member_names = [str(member) for member in family["members"]]
        member_weight = 1.0 / len(member_names)
        metrics = [
            *evaluate_walk_forward_returns(
                gross, scheme, metric_prefix="gross_excess"
            ),
            *evaluate_walk_forward_returns(net, scheme, metric_prefix="net_excess"),
            *extra_metrics,
        ]
        run_dir = store.publish(
            spec,
            metrics=metrics,
            members=[
                MemberWeight(atom_specs[member].run_id, member_weight)
                for member in member_names
            ],
            frames={
                "daily_returns": pd.DataFrame(
                    {"gross_excess_return": gross, "net_excess_return": net}
                ),
                "target_weights": target,
            },
            provenance={
                "alpha_definition": definition.path.as_posix(),
                "classification": "same-calendar market family after member crossing",
                "cost_application": "once on published crossed family target",
                "resolved_config": family,
                "true_forward_oos": False,
            },
        )
        manifests.append(run_dir / "manifest.json")
    registered = tuple(catalog.register_manifests(manifests))
    return MarketCohortSummary(
        atomic_runs=len(contract.atomic),
        family_runs=len(contract.families),
        registered_run_ids=registered,
        family_run_ids=tuple(family_ids),
    )


def _evaluate_target(
    target: pd.DataFrame,
    returns: pd.DataFrame,
    costs: AsymmetricCostContract,
) -> tuple[pd.Series, pd.Series, list[MetricValue]]:
    gross = (target * returns.fillna(0.0)).sum(axis=1)
    pretrade = target.shift(1).fillna(0.0)
    zero = pd.Series(0.0, index=target.index)
    breakdown = costs.evaluate_netted_orders(
        stock_target=target,
        stock_pretrade=pretrade,
        etf_target=zero,
        etf_pretrade=zero,
    )
    net = gross - breakdown["total_trade_cost"]
    extra = [
        MetricValue(
            "historical_full",
            "annualized_turnover",
            float(
                (
                    breakdown["stock_buy_turnover"]
                    + breakdown["stock_sell_turnover"]
                ).mean()
                * 252
            ),
        ),
        MetricValue(
            "historical_full",
            "annualized_trade_cost",
            float(breakdown["total_trade_cost"].mean() * 252),
        ),
    ]
    return gross, net, extra


def _read_target(path: Path, returns: pd.DataFrame) -> pd.DataFrame:
    target = pd.read_parquet(path)
    if not isinstance(target.index, pd.DatetimeIndex):
        if "date" not in target.columns:
            raise TypeError(f"Target has no DatetimeIndex or date column: {path}")
        target = target.set_index(pd.to_datetime(target.pop("date")))
    target.index = pd.DatetimeIndex(target.index)
    return target.reindex(index=returns.index, columns=returns.columns).fillna(0.0)


def _mapping_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of mappings.")
    return value


def _hash_payload(payload: Mapping[str, Any] | list[Any] | object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
