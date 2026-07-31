"""WFARunner generic market-adapter factory pass-through.

Host applications may need to wrap the adapter Echolon would normally build
with additional generic setup before any optimizer/backtest uses it. The hook is
mechanism-only: default None preserves the existing EngineFactory path.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock


def _make_runner(tmp_path, **kwargs):
    from echolon.backtest.wfa.runner import WFARunner
    from echolon.config.paths_config import PathsConfig

    return WFARunner(
        ctx=MagicMock(),
        config=MagicMock(),
        optuna_config=MagicMock(),
        backtest_config=MagicMock(),
        paths=PathsConfig(project_root=tmp_path),
        **kwargs,
    )


def test_init_default_market_adapter_factory_is_none(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.market_adapter_factory is None


def test_init_stores_custom_market_adapter_factory(tmp_path):
    def factory(*, ctx, paths):
        return object()

    runner = _make_runner(tmp_path, market_adapter_factory=factory)
    assert runner.market_adapter_factory is factory


def test_run_uses_market_adapter_factory_source_pin():
    from echolon.backtest.wfa.runner import WFARunner

    source = inspect.getsource(WFARunner.run)
    assert "self.market_adapter_factory is not None" in source
    assert "market_adapter = self.market_adapter_factory(" in source
    assert "market_adapter = EngineFactory.create_market_adapter(" in source
