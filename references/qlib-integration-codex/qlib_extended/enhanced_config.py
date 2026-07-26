from __future__ import annotations

from typing import Any, Mapping

from .backtest_schema import EnhancedIndexConfig


def parse_enhanced_index_config(
    raw: object,
    *,
    error_type: type[ValueError],
) -> EnhancedIndexConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise error_type("backtest.enhanced_index must be a mapping")
    allowed = {
        "lookthrough",
        "lower_bounds",
        "upper_bounds",
        "transaction_cost",
        "turnover_penalty",
        "risk_penalty",
        "cash_lower",
        "cash_upper",
        "solver",
    }
    unknown = sorted(set(raw).difference(allowed))
    if unknown:
        raise error_type(f"unknown backtest.enhanced_index keys: {unknown}")
    return EnhancedIndexConfig(
        lookthrough=_nested_float_mapping(
            raw, "lookthrough", error_type=error_type
        ),
        lower_bounds=_float_mapping(
            raw, "lower_bounds", error_type=error_type
        ),
        upper_bounds=_float_mapping(
            raw, "upper_bounds", error_type=error_type
        ),
        transaction_cost=_float_mapping(
            raw, "transaction_cost", error_type=error_type
        ),
        turnover_penalty=float(raw.get("turnover_penalty", 0.0)),
        risk_penalty=float(raw.get("risk_penalty", 0.0)),
        cash_lower=float(raw.get("cash_lower", 0.0)),
        cash_upper=float(raw.get("cash_upper", 1.0)),
        solver=str(raw.get("solver", "CLARABEL")),
    )


def validate_enhanced_index_config(
    config: EnhancedIndexConfig | None,
    *,
    target_semantics: str,
    error_type: type[ValueError],
) -> None:
    if target_semantics == "enhanced_index" and config is None:
        raise error_type(
            "enhanced_index target_semantics requires enhanced_index config"
        )
    if target_semantics != "enhanced_index" and config is not None:
        raise error_type(
            "enhanced_index config requires enhanced_index target_semantics"
        )
    if config is None:
        return
    if config.turnover_penalty < 0 or config.risk_penalty < 0:
        raise error_type("enhanced_index penalties must be non-negative")
    if not 0 <= config.cash_lower <= config.cash_upper <= 1:
        raise error_type(
            "enhanced_index cash bounds must satisfy 0 <= lower <= upper <= 1"
        )
    if not config.solver:
        raise error_type("enhanced_index solver must not be empty")


def _required_mapping(
    value: Mapping[str, Any],
    key: str,
    *,
    error_type: type[ValueError],
) -> Mapping[str, Any]:
    if key not in value or not isinstance(value[key], Mapping):
        raise error_type(
            f"backtest.enhanced_index.{key} must be a mapping"
        )
    result = value[key]
    if not result:
        raise error_type(
            f"backtest.enhanced_index.{key} must not be empty"
        )
    return result


def _float_mapping(
    value: Mapping[str, Any],
    key: str,
    *,
    error_type: type[ValueError],
) -> dict[str, float]:
    raw = _required_mapping(value, key, error_type=error_type)
    try:
        return {str(name): float(item) for name, item in raw.items()}
    except (TypeError, ValueError) as exc:
        raise error_type(
            f"backtest.enhanced_index.{key} must contain numeric values"
        ) from exc


def _nested_float_mapping(
    value: Mapping[str, Any],
    key: str,
    *,
    error_type: type[ValueError],
) -> dict[str, dict[str, float]]:
    raw = _required_mapping(value, key, error_type=error_type)
    result: dict[str, dict[str, float]] = {}
    for row_name, row in raw.items():
        if not isinstance(row, Mapping) or not row:
            raise error_type(
                "backtest.enhanced_index."
                f"{key}.{row_name} must be a non-empty mapping"
            )
        try:
            result[str(row_name)] = {
                str(column): float(item) for column, item in row.items()
            }
        except (TypeError, ValueError) as exc:
            raise error_type(
                "backtest.enhanced_index."
                f"{key}.{row_name} must contain numeric values"
            ) from exc
    return result
