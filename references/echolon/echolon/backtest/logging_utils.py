"""
Backtest Module Logging Utilities
=================================

Centralized logging configuration and utilities for consistent, context-aware
terminal output across the backtest module.

This module provides:
- Context-aware logging setup (optimization/debug/best_trial)
- Structured log format helpers
- Workflow lifecycle logging (start/progress/success/failure)
- Component decision logging for strategy debugging

Logging Modes:
- optimization: Minimal logging (WARNING+) - only progress and errors
- summary: User-facing summary (INFO+ at top-level loggers, bar-loop loggers
  demoted to WARNING). No per-bar trace. Default for ``echolon hello`` and
  the non-verbose ``echolon backtest single`` path.
- debug: Full visibility - per-bar Risk/Entry/Exit/Sizer trace visible.
  Opt in via ``--verbose``.
- best_trial: Balanced logging (INFO+, per-bar trace ON) - used by deploy
  daily best-trial replay.

Message Format:
    [CONTEXT] Component | STATUS | key1=value1, key2=value2
"""

import logging
from contextvars import ContextVar
from typing import Literal, Optional, Dict, Any

# Custom log level between WARNING (30) and ERROR (40). Used for milestone
# events ("backtest finished", "trial result") that must be visible in
# optimization mode without abusing CRITICAL (reserved for "stop the process").
RESULT = 35
logging.addLevelName(RESULT, "RESULT")

# Type for execution contexts
RunContext = Literal["optimization", "summary", "debug", "best_trial"]

# Default is "summary" — safer than "debug" because callers that forget to
# set the context (e.g. tests that hit logger paths directly) won't flood
# stdout with per-bar trace lines.
_current_context: ContextVar[RunContext] = ContextVar("echolon_run_context", default="summary")


def set_run_context(context: RunContext) -> None:
    """Set the run context for the current async/thread context.

    ContextVar semantics: asyncio tasks and concurrent.futures workers each
    get an isolated copy, so parallel Optuna trials do not race.
    """
    _current_context.set(context)


def get_run_context() -> RunContext:
    """Read the run context for the current async/thread context."""
    return _current_context.get()


def setup_backtest_logging(run_context: RunContext) -> None:
    """
    Configure logging for backtest module based on execution context.

    This function sets up appropriate log levels for different execution modes:
    - optimization: Minimal logging (WARNING+) for high-throughput runs
    - debug: Full visibility (INFO+) for development and debugging
    - best_trial: Balanced logging (INFO+) for production runs

    Args:
        run_context: Execution mode controlling log verbosity
    """
    # Set module-level context for components to check
    set_run_context(run_context)

    if run_context == "optimization":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)

        # Quiet high-volume bar-level / trial-level loggers (ERROR+).
        # These are the modules that log inside tight loops.
        for logger_name in [
            "echolon.backtest",
            "echolon.backtest.engine",
            "echolon.backtest.engine.backtrader_strategy",
            "echolon.backtest.engine.backtrader_engine",
            "echolon.backtest.engine.backtest_runner",
            "echolon.backtest.engine.hooks.contract_aware.broker",
            "echolon.backtest.engine.hooks.contract_aware.hook",
            "echolon.backtest.engine.hooks.session_aware",
            "echolon.backtest.metrics.mfe_mae",
            "echolon.backtest.optimization.optuna_study",
            "echolon.backtest.wfa.runner",
            "echolon.indicators.engine.processor",
        ]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

        # Suppress backtrader's internal logging
        logging.getLogger("backtrader").setLevel(logging.ERROR)
        logging.getLogger("backtrader.broker").setLevel(logging.ERROR)
        logging.getLogger("backtrader.cerebro").setLevel(logging.ERROR)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)

    elif run_context == "summary":
        # User-facing default. Root at INFO so workflow milestones
        # ([BACKTEST_RUNNER] Complete, [STRATEGY_BRIDGE] Indicators, …)
        # remain visible, but bar-loop loggers demoted to WARNING so the
        # per-bar Risk/Entry/Sizer trace doesn't drown the summary line.
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        for logger_name in [
            "echolon.backtest.engine.backtrader_strategy",
            "echolon.strategy.component",
            "echolon.backtest.engine.hooks.contract_aware.broker",
            "echolon.backtest.engine.hooks.contract_aware.hook",
            "echolon.backtest.engine.hooks.session_aware",
        ]:
            logging.getLogger(logger_name).setLevel(logging.WARNING)

        # Backtrader internals are noisy at INFO; user doesn't need them.
        logging.getLogger("backtrader").setLevel(logging.WARNING)
        logging.getLogger("matplotlib").setLevel(logging.WARNING)

    elif run_context == "debug":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)  # NOT DEBUG — per-module opt-in via ECHOLON_DEBUG_MODULES (Phase 3)

        for logger_name in [
            "echolon.backtest",
            "echolon.backtest.engine.backtrader_strategy",
            "echolon.indicators.engine.processor",
        ]:
            logging.getLogger(logger_name).setLevel(logging.INFO)

        logging.getLogger("matplotlib").setLevel(logging.WARNING)

    elif run_context == "best_trial":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        logging.getLogger("echolon.backtest").setLevel(logging.INFO)
        logging.getLogger("echolon.backtest.engine.backtrader_strategy").setLevel(logging.INFO)

        # Suppress noisy sub-components
        logging.getLogger("echolon.backtest.engine.hooks.contract_aware.broker").setLevel(logging.WARNING)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_workflow_start(context: RunContext, workflow: str, **kwargs) -> None:
    """
    Log workflow start with consistent format.

    Format: "[CONTEXT] Workflow | START | key1=value1, key2=value2"

    Args:
        context: Execution context (optimization/debug/best_trial)
        workflow: Workflow name (e.g., "Backtest", "DataPrep::Indicators")
        **kwargs: Additional details to log (key=value pairs)
    """
    logger = logging.getLogger("backtest")
    details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"[{context.upper()}] {workflow} | START"
    if details:
        msg += f" | {details}"
    logger.warning(msg)


def log_workflow_progress(
    context: RunContext,
    workflow: str,
    completed: int,
    total: int,
    extra: Optional[str] = None
) -> None:
    """
    Log workflow progress with percentage and optional extra info.

    Format: "[CONTEXT] Workflow | PROGRESS | 50/100 (50.0%)[, extra]"

    Args:
        context: Execution context
        workflow: Workflow name
        completed: Number of completed items
        total: Total number of items
        extra: Optional extra information (e.g., "ETA: 5min")
    """
    logger = logging.getLogger("backtest")
    pct = (completed / total) * 100 if total > 0 else 0
    msg = f"[{context.upper()}] {workflow} | PROGRESS | {completed}/{total} ({pct:.1f}%)"
    if extra:
        msg += f", {extra}"
    logger.warning(msg)


def log_workflow_success(context: RunContext, workflow: str, **metrics) -> None:
    """
    Log workflow success with metrics.

    Format: "[CONTEXT] Workflow | SUCCESS | metric1=value1, metric2=value2"

    Args:
        context: Execution context
        workflow: Workflow name
        **metrics: Success metrics to log (key=value pairs)
    """
    logger = logging.getLogger("backtest")
    details = ", ".join(f"{k}={v}" for k, v in metrics.items())
    msg = f"[{context.upper()}] {workflow} | SUCCESS"
    if details:
        msg += f" | {details}"
    logger.log(RESULT, msg)


def log_workflow_failure(
    context: RunContext,
    workflow: str,
    error: Exception | str,
) -> None:
    """
    Log workflow failure. Accepts either an exception (preferred — traceback
    is captured automatically via exc_info) or a plain string.

    Format: "[CONTEXT] Workflow | FAILURE | <type: msg or string>"

    Args:
        context: Execution context
        workflow: Workflow name
        error: Exception instance (traceback captured) OR a plain string
    """
    logger = logging.getLogger("backtest")
    if isinstance(error, BaseException):
        logger.critical(
            f"[{context.upper()}] {workflow} | FAILURE | {type(error).__name__}: {error}",
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.critical(f"[{context.upper()}] {workflow} | FAILURE | {error}")


def log_workflow_info(context: RunContext, workflow: str, message: str) -> None:
    """
    Log informational message for workflow.

    Format: "[CONTEXT] Workflow | INFO | message"

    Args:
        context: Execution context
        workflow: Workflow name
        message: Information message
    """
    logger = logging.getLogger("backtest")
    logger.info(f"[{context.upper()}] {workflow} | INFO | {message}")


def log_result_summary(
    context: RunContext,
    workflow: str,
    sharpe: float,
    total_return: float,
    max_drawdown: float,
    num_trades: int,
    **extra_metrics
) -> None:
    """
    Log comprehensive result summary for backtest runs.

    This creates a RESULT level log that's always visible and easily parseable
    by automated tools (e.g., debugger_agent.py).

    Format: "[CONTEXT] Workflow | RESULT SUMMARY | Sharpe: X.XXX | Return: X.XX% | ..."

    Args:
        context: Execution context
        workflow: Workflow name
        sharpe: Sharpe ratio
        total_return: Total return percentage
        max_drawdown: Maximum drawdown percentage
        num_trades: Number of trades
        **extra_metrics: Additional metrics (e.g., win_rate=55.2)
    """
    logger = logging.getLogger("backtest")

    # Format core metrics
    core_metrics = (
        f"Sharpe: {sharpe:.3f} | "
        f"Total Return: {total_return:.2f}% | "
        f"Max DD: {max_drawdown:.2f}% | "
        f"Trades: {num_trades}"
    )

    # Add extra metrics if provided
    if extra_metrics:
        extra = " | ".join(f"{k.replace('_', ' ').title()}: {v:.2f}" if isinstance(v, float)
                          else f"{k.replace('_', ' ').title()}: {v}"
                          for k, v in extra_metrics.items())
        core_metrics += f" | {extra}"

    logger.log(RESULT, f"[{context.upper()}] {workflow} | RESULT SUMMARY | {core_metrics}")


def log_zero_trades_warning(
    context: RunContext,
    workflow: str,
    bars_processed: int,
    entry_signals_generated: int = 0,
    entry_signals_blocked: int = 0,
    risk_blocks: int = 0,
) -> None:
    """
    Log warning when backtest produces zero trades with diagnostic info.

    This creates a WARNING level log that helps debugger_agent identify
    why no trades were executed (signal generation vs risk blocking).

    Format: "[CONTEXT] Workflow | ZERO TRADES | bars=N, signals=N, blocked=N, risk_blocks=N"

    Args:
        context: Execution context
        workflow: Workflow name
        bars_processed: Total bars processed
        entry_signals_generated: Number of entry signals generated
        entry_signals_blocked: Number of signals blocked by filters
        risk_blocks: Number of signals blocked by risk manager
    """
    logger = logging.getLogger("backtest")

    diagnostics = (
        f"bars={bars_processed}, "
        f"entry_signals={entry_signals_generated}, "
        f"signals_blocked={entry_signals_blocked}, "
        f"risk_blocks={risk_blocks}"
    )

    # Provide diagnostic guidance
    if entry_signals_generated == 0:
        hint = "HINT: No entry signals generated - check entry conditions"
    elif entry_signals_blocked + risk_blocks >= entry_signals_generated:
        hint = "HINT: All signals blocked - check filter/risk thresholds"
    else:
        hint = "HINT: Signals generated but not executed - check order logic"

    logger.warning(
        f"[{context.upper()}] {workflow} | ZERO TRADES WARNING | {diagnostics} | {hint}"
    )


def should_log_details(run_context: RunContext) -> bool:
    """
    Determine if detailed (per-bar) logging should be enabled based on context.

    Gates the per-bar Risk/Entry/Exit/Sizer trace and the per-bar
    ``[CONTEXT] Bar N | START/END`` lines. The other "verbose" logger
    levels (workflow_start, workflow_complete, indicator-bridge counts)
    are controlled by ``setup_backtest_logging``, not by this gate.

    - optimization: False (silent — high-throughput Optuna trials)
    - summary: False (user-facing summary — no per-bar trace)
    - debug: True (per-bar trace, opt in via ``--verbose``)
    - best_trial: True (per-bar trace for daily deploy replay)

    Args:
        run_context: Execution context

    Returns:
        True if per-bar trace should be logged
    """
    return run_context in ("debug", "best_trial")


def format_time_seconds(seconds: float) -> str:
    """
    Format seconds into human-readable string.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string (e.g., "4.2s", "1.5m", "2.3h")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_eta(remaining: int, rate: float) -> str:
    """
    Calculate and format ETA string.

    Args:
        remaining: Number of items remaining
        rate: Processing rate (items per second)

    Returns:
        Formatted ETA string (e.g., "ETA: 5.2m", "ETA: N/A")
    """
    if rate <= 0:
        return "ETA: N/A"

    eta_seconds = remaining / rate
    return f"ETA: {format_time_seconds(eta_seconds)}"
