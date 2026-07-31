"""Regression: logging_utils uses a custom RESULT level, not CRITICAL, for successes."""
import logging

from echolon.backtest import logging_utils


def test_result_level_is_defined():
    assert hasattr(logging_utils, "RESULT")
    assert logging_utils.RESULT == 35  # between WARNING (30) and ERROR (40)
    assert logging.getLevelName(35) == "RESULT"


def test_log_workflow_success_uses_result_level(caplog):
    with caplog.at_level(logging_utils.RESULT, logger="echolon.backtest.logging_utils"):
        logging_utils.log_workflow_success(
            context="debug", workflow="Backtest", sharpe=1.23
        )
    assert any(r.levelno == logging_utils.RESULT for r in caplog.records)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_log_result_summary_uses_result_level(caplog):
    with caplog.at_level(logging_utils.RESULT, logger="echolon.backtest.logging_utils"):
        logging_utils.log_result_summary(
            context="debug",
            workflow="Backtest",
            sharpe=1.0,
            total_return=10.0,
            max_drawdown=5.0,
            num_trades=42,
        )
    assert any(r.levelno == logging_utils.RESULT for r in caplog.records)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_log_workflow_failure_accepts_exception_and_records_traceback(caplog):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        logging_utils.log_workflow_failure(
            context="debug", workflow="Backtest", error=exc
        )
    # Record exists and has exc_info (traceback captured)
    records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert records, "CRITICAL-level record expected"
    assert records[-1].exc_info is not None
    assert records[-1].exc_info[0] is ValueError


def test_log_workflow_failure_accepts_string_backcompat(caplog):
    logging_utils.log_workflow_failure(
        context="debug", workflow="Backtest", error="simple string"
    )
    records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert records
    assert "simple string" in records[-1].message


import asyncio


def test_run_context_isolated_across_asyncio_tasks():
    """Parallel trials (asyncio or concurrent.futures) must not share run_context."""
    results = {}

    async def setter_a():
        logging_utils.set_run_context("optimization")
        await asyncio.sleep(0.01)
        results["a"] = logging_utils.get_run_context()

    async def setter_b():
        logging_utils.set_run_context("debug")
        await asyncio.sleep(0.01)
        results["b"] = logging_utils.get_run_context()

    async def runner():
        await asyncio.gather(setter_a(), setter_b())

    asyncio.run(runner())
    assert results["a"] == "optimization"
    assert results["b"] == "debug"


import importlib


def test_should_log_details_only_true_for_debug_and_best_trial():
    """Per-bar trace must be off for ``optimization`` and ``summary``,
    on for ``debug`` and ``best_trial``. Regression for v0.1.3 — the
    previous semantic ("on for everything except optimization") flooded
    ``echolon hello`` stdout with thousands of per-bar lines."""
    assert logging_utils.should_log_details("optimization") is False
    assert logging_utils.should_log_details("summary") is False
    assert logging_utils.should_log_details("debug") is True
    assert logging_utils.should_log_details("best_trial") is True


def test_setup_backtest_logging_summary_demotes_bar_loop_loggers():
    """``summary`` context must keep root at INFO but demote the bar-loop
    loggers (backtrader_strategy, strategy.component) to WARNING so that
    per-bar ``logger.info(...)`` calls are filtered out."""
    logging_utils.setup_backtest_logging("summary")

    # Root at INFO so workflow milestones show through.
    assert logging.getLogger().level == logging.INFO
    # Bar-loop loggers demoted to WARNING — per-bar info() calls suppressed.
    assert logging.getLogger("echolon.backtest.engine.backtrader_strategy").level == logging.WARNING
    assert logging.getLogger("echolon.strategy.component").level == logging.WARNING


def test_default_run_context_is_summary():
    """Default ContextVar value is ``summary`` — callers that hit logger
    paths without first calling setup_backtest_logging won't flood stdout."""
    # Reset to default by creating a fresh ContextVar via the module-level
    # default. We can't easily reset; but we can verify by reading the
    # default declared in the source.
    import inspect
    src = inspect.getsource(logging_utils)
    assert 'default="summary"' in src, "ContextVar default must be 'summary'"


def test_setup_backtest_logging_references_real_loggers():
    """setup_backtest_logging must not reference logger names that
    correspond to non-existent modules (regression: previously referenced
    modules.quant_engine.* which didn't exist post-reorg)."""
    import ast
    from pathlib import Path

    src_path = Path(importlib.import_module("echolon.backtest.logging_utils").__file__)
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    # Collect every string literal inside setup_backtest_logging that looks
    # like a dotted echolon.* logger name.
    logger_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "setup_backtest_logging":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    if sub.value.startswith("echolon."):
                        logger_names.append(sub.value)

    assert logger_names, "expected echolon.* logger names inside setup_backtest_logging"

    for name in logger_names:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            raise AssertionError(
                f"Logger name {name!r} referenced in setup_backtest_logging "
                f"does not resolve to an importable module: {exc}"
            )
