"""Verify all public modules are importable."""


def test_import_core():
    from echolon.strategy.base import BaseStrategy
    from echolon.strategy.component import BaseComponent
    from echolon.strategy.interfaces import (
        ITradingEngine,
        IMarketData,
        IPortfolio,
        IOrderManager,
    )
    assert BaseStrategy is not None
    assert BaseComponent is not None
    assert ITradingEngine is not None


def test_import_market_adapters():
    from echolon.markets.shfe.adapter import SHFEAdapter
    from echolon.markets.crypto.adapter import CryptoAdapter
    assert SHFEAdapter is not None
    assert CryptoAdapter is not None


def test_import_backtest():
    from echolon.backtest.engine.backtrader_engine import BacktraderEngine
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer
    from echolon.engine.factory import EngineFactory
    assert BacktraderEngine is not None
    assert OptunaOptimizer is not None
    assert EngineFactory is not None


def test_import_data_pipeline():
    from echolon.data import extractors, transformers, loaders
    assert extractors is not None


def test_import_indicators():
    from echolon.indicators import calculators
    assert calculators is not None


def test_import_config():
    from echolon.config import paths_config
    assert paths_config is not None
    assert paths_config.PathsConfig is not None


def test_import_deploy():
    from echolon.live import platforms
    assert platforms is not None


def test_public_api():
    """Top-level echolon namespace exposes the main public types."""
    import echolon

    assert echolon.__version__
    assert echolon.TradingContext is not None
    assert echolon.BacktestConfig is not None
    assert echolon.OptunaConfig is not None
    assert echolon.IndicatorConfig is not None
    assert echolon.quick_start is not None
