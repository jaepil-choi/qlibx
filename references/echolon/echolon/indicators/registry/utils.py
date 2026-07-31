"""
Indicator Registry Utils
=========================

Frequency-based routing for indicator functions.
Routes to appropriate calculator module based on trading frequency.

Usage:
    from echolon.indicators.registry.utils import get_function, get_indicator_info

    # For interday (daily bars)
    rsi_func = get_function("RSI", frequency="day")

    # For intraday (5-min bars)
    rsi_func = get_function("RSI", frequency="minute")
"""

import importlib
from typing import Optional, Callable, Dict, Any
import json
from pathlib import Path


def get_function(indicator_key: str, frequency: str = "day") -> Optional[Callable]:
    """
    Get the indicator calculation function based on frequency.

    Routes to appropriate calculator module:
    - "day", "daily", "interday" -> calculators/interday/
    - "minute", "intraday" -> calculators/intraday/

    Parameters
    ----------
    indicator_key : str
        Indicator name (e.g., 'RSI', 'MACD_LINE', 'MARKET_REGIME')
    frequency : str
        Data frequency ('day' or 'minute')

    Returns
    -------
    Callable or None
        Indicator calculation function
    """
    if frequency in ("minute", "intraday"):
        mapping_module = importlib.import_module(
            "echolon.indicators.calculators.intraday.indicator_mapping"
        )
    else:
        mapping_module = importlib.import_module(
            "echolon.indicators.calculators.interday.indicator_mapping"
        )

    return mapping_module.get_function(indicator_key)


def get_indicator_info(indicator_key: str, frequency: str = "day") -> Optional[Dict[str, Any]]:
    """
    Get indicator metadata (function name, cluster, file) based on frequency.

    Parameters
    ----------
    indicator_key : str
        Indicator name (e.g., 'RSI', 'VWAP')
    frequency : str
        Data frequency ('day' or 'minute')

    Returns
    -------
    Dict or None
        Indicator info with 'function', 'cluster', and 'file' keys
    """
    if frequency in ("minute", "intraday"):
        mapping_module = importlib.import_module(
            "echolon.indicators.calculators.intraday.indicator_mapping"
        )
    else:
        mapping_module = importlib.import_module(
            "echolon.indicators.calculators.interday.indicator_mapping"
        )

    return mapping_module.get_indicator_info(indicator_key)


def get_indicator_dictionary(frequency: str = "day") -> Dict[str, Any]:
    """
    Load the indicator dictionary for the specified frequency.

    Parameters
    ----------
    frequency : str
        Data frequency ('day' or 'minute')

    Returns
    -------
    Dict
        Indicator dictionary with clusters
    """
    base_path = Path(__file__).parent.parent / "calculators"

    if frequency in ("minute", "intraday"):
        dict_file = base_path / "intraday" / "indicator_dictionary.json"
    else:
        dict_file = base_path / "interday" / "indicator_dictionary.json"

    with open(dict_file, 'r') as f:
        return json.load(f)


def indicator_exists(indicator_key: str, frequency: str = "day") -> bool:
    """
    Check if an indicator exists for the specified frequency.

    Parameters
    ----------
    indicator_key : str
        Indicator name
    frequency : str
        Data frequency

    Returns
    -------
    bool
        True if indicator exists
    """
    info = get_indicator_info(indicator_key, frequency)
    return info is not None


