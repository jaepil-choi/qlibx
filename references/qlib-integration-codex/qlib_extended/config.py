from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .backtest_schema import (
    EnhancedIndexConfig,
    ExecutionConfig,
    MatchedCapitalizationConfig,
)
from .enhanced_config import (
    parse_enhanced_index_config,
    validate_enhanced_index_config,
)
from .matched_config import (
    parse_matched_capitalization_config,
    validate_matched_capitalization_config,
)


DEFAULT_COST_POLICY: Mapping[str, Mapping[str, float]] = {
    "stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0}
}

class ConfigurationError(ValueError):
    """Raised when the public project configuration violates its explicit schema."""


@dataclass(frozen=True)
class StoreConfig:
    catalog_uri: Path
    artifact_dir: Path


@dataclass(frozen=True)
class DatasetConfig:
    path: Path
    format: str
    value_column: str


@dataclass(frozen=True)
class StrategyConfig:
    callable_path: str
    datasets: Mapping[str, str]
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float
    execution_price: str
    universe: str
    benchmark_weight: str
    valuation_price: str | None = None
    position_unit_factor: str | None = None
    signal_lag: int = 1
    top_n: int = 1
    gross_exposure: float = 0.8
    cost_policy: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: dict(DEFAULT_COST_POLICY)
    )
    target_semantics: str = "long_only"
    matched_capitalization: MatchedCapitalizationConfig | None = None
    enhanced_index: EnhancedIndexConfig | None = None
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def __post_init__(self) -> None:
        if isinstance(self.matched_capitalization, Mapping):
            object.__setattr__(
                self,
                "matched_capitalization",
                MatchedCapitalizationConfig(**self.matched_capitalization),
            )
        if isinstance(self.execution, Mapping):
            object.__setattr__(self, "execution", ExecutionConfig(**self.execution))
        if isinstance(self.enhanced_index, Mapping):
            object.__setattr__(
                self,
                "enhanced_index",
                EnhancedIndexConfig(**self.enhanced_index),
            )

    def identity_payload(self) -> Mapping[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectConfig:
    path: Path
    store: StoreConfig
    datasets: Mapping[str, DatasetConfig]
    strategies: Mapping[str, StrategyConfig]
    backtest: BacktestConfig


def load_project_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise ConfigurationError(f"config does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ConfigurationError("project config must be a mapping")
    _reject_unknown(raw, {"version", "run_store", "data", "strategies", "backtest"}, "project")
    if raw.get("version") != 1:
        raise ConfigurationError("project version must be 1")
    base = config_path.parent
    store_raw = _mapping(raw, "run_store")
    _reject_unknown(store_raw, {"catalog_uri", "artifact_dir"}, "run_store")
    store = StoreConfig(
        catalog_uri=_resolve_path(base, _required_str(store_raw, "catalog_uri")),
        artifact_dir=_resolve_path(base, _required_str(store_raw, "artifact_dir")),
    )

    data_raw = _mapping(raw, "data")
    _reject_unknown(data_raw, {"datasets"}, "data")
    dataset_rows = _mapping(data_raw, "datasets")
    datasets: dict[str, DatasetConfig] = {}
    for name, value in dataset_rows.items():
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"dataset {name} must be a mapping")
        _reject_unknown(value, {"path", "format", "value_column"}, f"dataset {name}")
        format_name = _required_str(value, "format")
        if format_name != "parquet":
            raise ConfigurationError(f"dataset {name} format must be parquet")
        datasets[str(name)] = DatasetConfig(
            path=_resolve_path(base, _required_str(value, "path")),
            format=format_name,
            value_column=_required_str(value, "value_column"),
        )

    strategies_raw = _mapping(raw, "strategies")
    strategies: dict[str, StrategyConfig] = {}
    for strategy_id, value in strategies_raw.items():
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"strategy {strategy_id} must be a mapping")
        _reject_unknown(value, {"callable", "datasets", "parameters"}, f"strategy {strategy_id}")
        aliases = _mapping(value, "datasets")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ConfigurationError(f"strategy {strategy_id} parameters must be a mapping")
        strategies[str(strategy_id)] = StrategyConfig(
            callable_path=_required_str(value, "callable"),
            datasets={str(alias): str(name) for alias, name in aliases.items()},
            parameters=dict(parameters),
        )

    backtest_raw = _mapping(raw, "backtest")
    _reject_unknown(
        backtest_raw,
        {
            "initial_cash",
            "execution_price",
            "valuation_price",
            "position_unit_factor",
            "universe",
            "benchmark_weight",
            "signal_lag",
            "top_n",
            "gross_exposure",
            "cost_policy",
            "target_semantics",
            "matched_capitalization",
            "enhanced_index",
            "execution",
        },
        "backtest",
    )
    matched = parse_matched_capitalization_config(
        backtest_raw.get("matched_capitalization"),
        error_type=ConfigurationError,
    )
    enhanced = parse_enhanced_index_config(
        backtest_raw.get("enhanced_index"),
        error_type=ConfigurationError,
    )
    execution_raw = backtest_raw.get("execution", {})
    if not isinstance(execution_raw, Mapping):
        raise ConfigurationError("backtest.execution must be a mapping")
    _reject_unknown(
        execution_raw,
        {"volume", "max_volume_participation"},
        "backtest.execution",
    )
    execution = ExecutionConfig(
        volume=(
            None
            if execution_raw.get("volume") is None
            else _required_str(execution_raw, "volume")
        ),
        max_volume_participation=(
            None
            if execution_raw.get("max_volume_participation") is None
            else float(execution_raw["max_volume_participation"])
        ),
    )
    backtest = BacktestConfig(
        initial_cash=float(_required(backtest_raw, "initial_cash")),
        execution_price=_required_str(backtest_raw, "execution_price"),
        valuation_price=(
            None
            if backtest_raw.get("valuation_price") is None
            else _required_str(backtest_raw, "valuation_price")
        ),
        position_unit_factor=(
            None
            if backtest_raw.get("position_unit_factor") is None
            else _required_str(backtest_raw, "position_unit_factor")
        ),
        universe=_required_str(backtest_raw, "universe"),
        benchmark_weight=_required_str(backtest_raw, "benchmark_weight"),
        signal_lag=int(backtest_raw.get("signal_lag", 1)),
        top_n=int(backtest_raw.get("top_n", 1)),
        gross_exposure=float(backtest_raw.get("gross_exposure", 0.8)),
        cost_policy=backtest_raw.get("cost_policy", DEFAULT_COST_POLICY),
        target_semantics=str(backtest_raw.get("target_semantics", "long_only")),
        matched_capitalization=matched,
        enhanced_index=enhanced,
        execution=execution,
    )
    _validate_backtest(backtest)
    referenced = {
        *backtest_dataset_names(backtest),
        *(name for strategy in strategies.values() for name in strategy.datasets.values()),
    }
    missing = sorted(referenced.difference(datasets))
    if missing:
        raise ConfigurationError(f"unknown logical datasets: {missing}")
    return ProjectConfig(
        path=config_path,
        store=store,
        datasets=datasets,
        strategies=strategies,
        backtest=backtest,
    )


def backtest_dataset_names(config: BacktestConfig) -> tuple[str, ...]:
    names = [
        config.execution_price,
        config.universe,
        config.benchmark_weight,
    ]
    if config.position_unit_factor is not None:
        names.append(config.position_unit_factor)
    if config.valuation_price is not None:
        names.append(config.valuation_price)
    if config.execution.volume is not None:
        names.append(config.execution.volume)
    if config.matched_capitalization is not None:
        names.extend(
            [
                config.matched_capitalization.observed,
                config.matched_capitalization.tradable,
                config.matched_capitalization.shortable,
            ]
        )
    return tuple(names)


def _validate_backtest(config: BacktestConfig) -> None:
    if config.initial_cash <= 0:
        raise ConfigurationError("backtest initial_cash must be positive")
    if config.signal_lag < 0:
        raise ConfigurationError("backtest signal_lag must be non-negative")
    if config.top_n <= 0:
        raise ConfigurationError("backtest top_n must be positive")
    if not 0 < config.gross_exposure <= 1:
        raise ConfigurationError("backtest gross_exposure must be in (0, 1]")
    if config.target_semantics not in {
        "long_only",
        "target_weight",
        "signed_weight",
        "enhanced_index",
    }:
        raise ConfigurationError(
            "backtest target_semantics must be long_only, target_weight, "
            "signed_weight or enhanced_index"
        )
    matched = config.matched_capitalization
    enhanced = config.enhanced_index
    validate_matched_capitalization_config(
        matched,
        target_semantics=config.target_semantics,
        initial_cash=config.initial_cash,
        error_type=ConfigurationError,
    )
    validate_enhanced_index_config(
        enhanced,
        target_semantics=config.target_semantics,
        error_type=ConfigurationError,
    )
    participation = config.execution.max_volume_participation
    if participation is not None and not 0 < participation <= 1:
        raise ConfigurationError(
            "backtest.execution max_volume_participation must be in (0, 1]"
        )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = _required(value, key)
    if not isinstance(result, Mapping):
        raise ConfigurationError(f"{key} must be a mapping")
    return result


def _required(value: Mapping[str, Any], key: str) -> Any:
    if key not in value:
        raise ConfigurationError(f"missing required config key: {key}")
    return value[key]


def _required_str(value: Mapping[str, Any], key: str) -> str:
    result = _required(value, key)
    if not isinstance(result, str) or not result.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return result.strip()


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise ConfigurationError(f"unknown {context} keys: {unknown}")


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()
