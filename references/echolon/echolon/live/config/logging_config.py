"""
Logging Configuration for Deploy
=================================

Centralized logging for the live trading system.
Ported from QTS_deploy/utils/logging_config.py.

All deploy loggers write to a single daily log file (qts_system.log)
for unified debugging. Strategy logging (CSV) is separate.
"""

import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict


# Global state
_loggers: Dict[str, logging.Logger] = {}
_logging_lock = threading.Lock()
_file_handler_lock = threading.Lock()
_shared_file_handler: Optional[logging.Handler] = None
_logs_dir: Optional[Path] = None


class DeployFormatter(logging.Formatter):
    """Formatter for deploy logs."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
        )


class DailyRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Daily rotating file handler with cleanup."""

    def __init__(self, base_filename: str, **kwargs):
        super().__init__(
            filename=base_filename,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8',
            **kwargs
        )
        self.suffix = "%Y%m%d"


def init_logging(logs_dir: str) -> None:
    """
    Initialize the logging system with a logs directory.

    Args:
        logs_dir: Directory for log files
    """
    global _logs_dir
    _logs_dir = Path(logs_dir)
    _logs_dir.mkdir(parents=True, exist_ok=True)


def _get_shared_file_handler() -> Optional[logging.Handler]:
    """Get or create the shared file handler."""
    global _shared_file_handler

    with _file_handler_lock:
        if _shared_file_handler is None and _logs_dir is not None:
            log_file = _logs_dir / "qts_system.log"
            _shared_file_handler = DailyRotatingFileHandler(str(log_file))
            _shared_file_handler.setFormatter(DeployFormatter())
            _shared_file_handler.setLevel(logging.DEBUG)
        return _shared_file_handler


def get_deploy_logger(
    name: str,
    level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """
    Get or create a deploy logger.

    All loggers write to the same daily log file.

    Args:
        name: Logger name
        level: Log level
        log_to_file: Whether to write to file
        log_to_console: Whether to write to console

    Returns:
        Configured logger
    """
    with _logging_lock:
        if name in _loggers:
            return _loggers[name]

        logger = logging.getLogger(f"deploy.{name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = False

        if log_to_file:
            file_handler = _get_shared_file_handler()
            if file_handler is not None:
                logger.addHandler(file_handler)

        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, level.upper()))
            console_handler.setFormatter(DeployFormatter())
            logger.addHandler(console_handler)

        _loggers[name] = logger
        return logger


def shutdown_logging() -> None:
    """Gracefully shutdown the logging system."""
    global _shared_file_handler

    with _file_handler_lock:
        if _shared_file_handler is not None:
            try:
                _shared_file_handler.close()
            except Exception:
                pass
            _shared_file_handler = None

    with _logging_lock:
        for logger in _loggers.values():
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception:
                    pass
        _loggers.clear()


def cleanup_old_logs(days_to_keep: int = 30) -> None:
    """Remove log files older than specified days."""
    if _logs_dir is None:
        return

    cutoff_date = datetime.now() - timedelta(days=days_to_keep)

    for log_file in _logs_dir.glob("qts_system_*.log"):
        try:
            file_date = datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_date < cutoff_date:
                log_file.unlink()
        except Exception:
            pass
