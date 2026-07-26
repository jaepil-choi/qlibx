from __future__ import annotations

from typing import Mapping

from .backtest_schema import MatchedCapitalizationConfig


def parse_matched_capitalization_config(
    raw: object,
    *,
    error_type: type[ValueError],
) -> MatchedCapitalizationConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise error_type("backtest.matched_capitalization must be a mapping")
    allowed = {
        "observed",
        "tradable",
        "shortable",
        "per_name_short_cap",
        "safety_multiplier",
        "inventory_readiness",
        "inventory_retention",
        "active_booksize",
    }
    unknown = sorted(set(raw).difference(allowed))
    if unknown:
        raise error_type(
            f"unknown backtest.matched_capitalization keys: {unknown}"
        )
    return MatchedCapitalizationConfig(
        observed=_required_str(raw, "observed", error_type=error_type),
        tradable=_required_str(raw, "tradable", error_type=error_type),
        shortable=_required_str(raw, "shortable", error_type=error_type),
        per_name_short_cap=float(
            _required(raw, "per_name_short_cap", error_type=error_type)
        ),
        safety_multiplier=float(raw.get("safety_multiplier", 1.0)),
        inventory_readiness=str(raw.get("inventory_readiness", "same_bar")),
        inventory_retention=str(raw.get("inventory_retention", "retained")),
        active_booksize=(
            None
            if raw.get("active_booksize") is None
            else float(raw["active_booksize"])
        ),
    )


def validate_matched_capitalization_config(
    config: MatchedCapitalizationConfig | None,
    *,
    target_semantics: str,
    initial_cash: float,
    error_type: type[ValueError],
) -> None:
    if target_semantics == "signed_weight" and config is None:
        raise error_type(
            "signed_weight target_semantics requires matched_capitalization"
        )
    if target_semantics != "signed_weight" and config is not None:
        raise error_type(
            "matched_capitalization requires signed_weight target_semantics"
        )
    if config is None:
        return
    if not 0 < config.per_name_short_cap <= 1:
        raise error_type(
            "matched_capitalization per_name_short_cap must be in (0, 1]"
        )
    if config.safety_multiplier < 1:
        raise error_type(
            "matched_capitalization safety_multiplier must be at least 1"
        )
    if config.inventory_readiness != "same_bar":
        raise error_type(
            "matched_capitalization inventory_readiness currently supports same_bar"
        )
    if config.inventory_retention not in {"retained", "active_short_only"}:
        raise error_type(
            "matched_capitalization inventory_retention must be retained or "
            "active_short_only"
        )
    if config.active_booksize is not None and not (
        0 < config.active_booksize <= initial_cash
    ):
        raise error_type(
            "matched_capitalization active_booksize must be positive and no "
            "greater than backtest initial_cash"
        )


def _required(
    value: Mapping[object, object],
    key: str,
    *,
    error_type: type[ValueError],
) -> object:
    if key not in value:
        raise error_type(f"missing required config key: {key}")
    return value[key]


def _required_str(
    value: Mapping[object, object],
    key: str,
    *,
    error_type: type[ValueError],
) -> str:
    result = _required(value, key, error_type=error_type)
    if not isinstance(result, str) or not result.strip():
        raise error_type(f"{key} must be a non-empty string")
    return result.strip()
