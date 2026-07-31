"""
Intraday Indicator Mapping Registry
===================================

Maps indicator names to their calculation functions for intraday data.
Intraday indicators include:
- Session-aware indicators (VWAP, opening range, session levels)
- Time-based features (bar of day, session phase)
- TA-Lib indicators with intraday-calibrated periods
- Two-layer context system:
  - SESSION_PHASE: Time-based session classification (PRIMARY)
  - VOLATILITY_STATE: ATR-based volatility level (SECONDARY)

NOTE: Trend-based regime (trending_up/down) does NOT work for intraday due to
mean-reversion dynamics. Use SESSION_PHASE + VOLATILITY_STATE instead.
"""

# File name mappings for intraday calculators
INDICATOR_FILES = {
    "talib_indicator": "ta_lib",
    "market_context": "market_context",
    "session_indicators": "indicators",
}

# Intraday-specific indicator mapping
# Maps indicator key to function name + file
# All functions use intraday-calibrated default periods
INTRADAY_INDICATOR_MAPPING = {
    # =========================================================================
    # SECTION 1: INDICATORS WITH LOOKBACK PERIOD
    # =========================================================================

    # Volatility Indicators
    "ATR": {"function": "atr", "file": INDICATOR_FILES["talib_indicator"]},
    "NATR": {"function": "natr", "file": INDICATOR_FILES["talib_indicator"]},

    # Momentum Indicators
    "ADX": {"function": "adx", "file": INDICATOR_FILES["talib_indicator"]},
    "ADXR": {"function": "adxr", "file": INDICATOR_FILES["talib_indicator"]},
    "AROON_DOWN": {"function": "aroon", "file": INDICATOR_FILES["talib_indicator"]},
    "AROON_UP": {"function": "aroon", "file": INDICATOR_FILES["talib_indicator"]},
    "AROONOSC": {"function": "aroonosc", "file": INDICATOR_FILES["talib_indicator"]},
    "CCI": {"function": "cci", "file": INDICATOR_FILES["talib_indicator"]},
    "CMO": {"function": "cmo", "file": INDICATOR_FILES["talib_indicator"]},
    "DX": {"function": "dx", "file": INDICATOR_FILES["talib_indicator"]},
    "MFI": {"function": "mfi", "file": INDICATOR_FILES["talib_indicator"]},
    "MINUS_DI": {"function": "minus_di", "file": INDICATOR_FILES["talib_indicator"]},
    "MINUS_DM": {"function": "minus_dm", "file": INDICATOR_FILES["talib_indicator"]},
    "MOM": {"function": "mom", "file": INDICATOR_FILES["talib_indicator"]},
    "PLUS_DI": {"function": "plus_di", "file": INDICATOR_FILES["talib_indicator"]},
    "PLUS_DM": {"function": "plus_dm", "file": INDICATOR_FILES["talib_indicator"]},
    "ROC": {"function": "roc", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCP": {"function": "rocp", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCR": {"function": "rocr", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCR100": {"function": "rocr100", "file": INDICATOR_FILES["talib_indicator"]},
    "RSI": {"function": "rsi", "file": INDICATOR_FILES["talib_indicator"]},
    "TRIX": {"function": "trix", "file": INDICATOR_FILES["talib_indicator"]},
    "WILLR": {"function": "willr", "file": INDICATOR_FILES["talib_indicator"]},

    # Overlap Studies (Moving Averages)
    "DEMA": {"function": "dema", "file": INDICATOR_FILES["talib_indicator"]},
    "EMA": {"function": "ema", "file": INDICATOR_FILES["talib_indicator"]},
    "KAMA": {"function": "kama", "file": INDICATOR_FILES["talib_indicator"]},
    "MA": {"function": "ma", "file": INDICATOR_FILES["talib_indicator"]},
    "MIDPOINT": {"function": "midpoint", "file": INDICATOR_FILES["talib_indicator"]},
    "MIDPRICE": {"function": "midprice", "file": INDICATOR_FILES["talib_indicator"]},
    "SMA": {"function": "sma", "file": INDICATOR_FILES["talib_indicator"]},
    "TEMA": {"function": "tema", "file": INDICATOR_FILES["talib_indicator"]},
    "TRIMA": {"function": "trima", "file": INDICATOR_FILES["talib_indicator"]},
    "WMA": {"function": "wma", "file": INDICATOR_FILES["talib_indicator"]},

    # Math Operators
    "MAX": {"function": "max_func", "file": INDICATOR_FILES["talib_indicator"]},
    "MAXINDEX": {"function": "maxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MIN": {"function": "min_func", "file": INDICATOR_FILES["talib_indicator"]},
    "MININDEX": {"function": "minindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MIN": {"function": "minmax", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MAX": {"function": "minmax", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MIN": {"function": "minmaxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MAX": {"function": "minmaxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "SUM": {"function": "sum_func", "file": INDICATOR_FILES["talib_indicator"]},
    "HIGHEST_HIGH": {"function": "highest_high", "file": INDICATOR_FILES["talib_indicator"]},
    "LOWEST_LOW": {"function": "lowest_low", "file": INDICATOR_FILES["talib_indicator"]},

    # Statistic Functions
    "BETA": {"function": "beta", "file": INDICATOR_FILES["talib_indicator"]},
    "CORREL": {"function": "correl", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG": {"function": "linearreg", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_ANGLE": {"function": "linearreg_angle", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_INTERCEPT": {"function": "linearreg_intercept", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_SLOPE": {"function": "linearreg_slope", "file": INDICATOR_FILES["talib_indicator"]},
    "TSF": {"function": "tsf", "file": INDICATOR_FILES["talib_indicator"]},

    # =========================================================================
    # SECTION 2: INDICATORS WITHOUT LOOKBACK PERIOD
    # =========================================================================
    "BOP": {"function": "bop", "file": INDICATOR_FILES["talib_indicator"]},
    "ADD": {"function": "add", "file": INDICATOR_FILES["talib_indicator"]},
    "DIV": {"function": "div", "file": INDICATOR_FILES["talib_indicator"]},
    "MULT": {"function": "mult", "file": INDICATOR_FILES["talib_indicator"]},
    "SUB": {"function": "sub", "file": INDICATOR_FILES["talib_indicator"]},
    "ACOS": {"function": "acos", "file": INDICATOR_FILES["talib_indicator"]},
    "ASIN": {"function": "asin", "file": INDICATOR_FILES["talib_indicator"]},
    "ATAN": {"function": "atan", "file": INDICATOR_FILES["talib_indicator"]},
    "CEIL": {"function": "ceil", "file": INDICATOR_FILES["talib_indicator"]},
    "COS": {"function": "cos", "file": INDICATOR_FILES["talib_indicator"]},
    "FLOOR": {"function": "floor", "file": INDICATOR_FILES["talib_indicator"]},
    "LN": {"function": "ln", "file": INDICATOR_FILES["talib_indicator"]},
    "LOG10": {"function": "log10", "file": INDICATOR_FILES["talib_indicator"]},
    "SIN": {"function": "sin", "file": INDICATOR_FILES["talib_indicator"]},
    "SQRT": {"function": "sqrt", "file": INDICATOR_FILES["talib_indicator"]},
    "TAN": {"function": "tan", "file": INDICATOR_FILES["talib_indicator"]},
    "TANH": {"function": "tanh", "file": INDICATOR_FILES["talib_indicator"]},
    "AVGPRICE": {"function": "avgprice", "file": INDICATOR_FILES["talib_indicator"]},
    "MEDPRICE": {"function": "medprice", "file": INDICATOR_FILES["talib_indicator"]},
    "TYPPRICE": {"function": "typprice", "file": INDICATOR_FILES["talib_indicator"]},
    "WCLPRICE": {"function": "wclprice", "file": INDICATOR_FILES["talib_indicator"]},
    "TRANGE": {"function": "trange", "file": INDICATOR_FILES["talib_indicator"]},
    "AD": {"function": "ad", "file": INDICATOR_FILES["talib_indicator"]},
    "OBV": {"function": "obv", "file": INDICATOR_FILES["talib_indicator"]},

    # Cycle Indicators
    "HT_DCPERIOD": {"function": "ht_dcperiod", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPHASE": {"function": "ht_dcphase", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_INPHASE": {"function": "ht_phasor", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_QUADRATURE": {"function": "ht_phasor", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_SINE": {"function": "ht_sine", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_LEADSINE": {"function": "ht_sine", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDMODE": {"function": "ht_trendmode", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDLINE": {"function": "ht_trendline", "file": INDICATOR_FILES["talib_indicator"]},

    # Candlestick Patterns (selection)
    "CDL2CROWS": {"function": "cdl2crows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3BLACKCROWS": {"function": "cdl3blackcrows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3INSIDE": {"function": "cdl3inside", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3OUTSIDE": {"function": "cdl3outside", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3WHITESOLDIERS": {"function": "cdl3whitesoldiers", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJI": {"function": "cdldoji", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLENGULFING": {"function": "cdlengulfing", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHAMMER": {"function": "cdlhammer", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMI": {"function": "cdlharami", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMARUBOZU": {"function": "cdlmarubozu", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHOOTINGSTAR": {"function": "cdlshootingstar", "file": INDICATOR_FILES["talib_indicator"]},

    # =========================================================================
    # SECTION 3: INDICATORS WITH SPECIAL PARAMETERS
    # =========================================================================
    "APO": {"function": "apo", "file": INDICATOR_FILES["talib_indicator"]},
    "PPO": {"function": "ppo", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_LINE": {"function": "macd", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_SIGNAL": {"function": "macd", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_HISTOGRAM": {"function": "macd", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_LINE": {"function": "macdext", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_SIGNAL": {"function": "macdext", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_HISTOGRAM": {"function": "macdext", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_LINE": {"function": "macdfix", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_SIGNAL": {"function": "macdfix", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_HISTOGRAM": {"function": "macdfix", "file": INDICATOR_FILES["talib_indicator"]},
    "ULTOSC": {"function": "ultosc", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCH_SLOWK": {"function": "stoch", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCH_SLOWD": {"function": "stoch", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHF_FASTK": {"function": "stochf", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHF_FASTD": {"function": "stochf", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHRSI_FASTK": {"function": "stochrsi", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHRSI_FASTD": {"function": "stochrsi", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_UPPER": {"function": "bbands", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_MIDDLE": {"function": "bbands", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_LOWER": {"function": "bbands", "file": INDICATOR_FILES["talib_indicator"]},
    "MAMA": {"function": "mama", "file": INDICATOR_FILES["talib_indicator"]},
    "FAMA": {"function": "mama", "file": INDICATOR_FILES["talib_indicator"]},
    "MAVP": {"function": "mavp", "file": INDICATOR_FILES["talib_indicator"]},
    "SAR": {"function": "sar", "file": INDICATOR_FILES["talib_indicator"]},
    "SAREXT": {"function": "sarext", "file": INDICATOR_FILES["talib_indicator"]},
    "T3": {"function": "t3", "file": INDICATOR_FILES["talib_indicator"]},
    "STDDEV": {"function": "stddev", "file": INDICATOR_FILES["talib_indicator"]},
    "VAR": {"function": "var", "file": INDICATOR_FILES["talib_indicator"]},
    "ADOSC": {"function": "adosc", "file": INDICATOR_FILES["talib_indicator"]},

    # =========================================================================
    # SECTION 4: INTRADAY-SPECIFIC INDICATORS
    # =========================================================================

    # Session Indicators - Individual Wrappers (for market_metrics analysis)
    # NOTE: These use indicators_without_lookback as they are computed per-bar without lookback
    "VWAP": {"function": "vwap", "file": INDICATOR_FILES["session_indicators"]},
    "VWAP_DISTANCE_PCT": {"function": "vwap_distance_pct", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_HIGH": {"function": "session_high", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_LOW": {"function": "session_low", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_POSITION_PCT": {"function": "session_position_pct", "file": INDICATOR_FILES["session_indicators"]},
    "VOLUME_PERCENTILE": {"function": "volume_percentile", "file": INDICATOR_FILES["session_indicators"]},
    "VOLUME_VS_SESSION_AVG": {"function": "volume_vs_session_avg", "file": INDICATOR_FILES["session_indicators"]},

    # Opening Range Indicators
    "NIGHT_OR_HIGH": {"function": "night_or_high", "file": INDICATOR_FILES["session_indicators"]},
    "NIGHT_OR_LOW": {"function": "night_or_low", "file": INDICATOR_FILES["session_indicators"]},
    "DAY_OR_HIGH": {"function": "day_or_high", "file": INDICATOR_FILES["session_indicators"]},
    "DAY_OR_LOW": {"function": "day_or_low", "file": INDICATOR_FILES["session_indicators"]},
    "OR_BREAKOUT": {"function": "or_breakout", "file": INDICATOR_FILES["session_indicators"]},

    # Time Features
    "BAR_OF_DAY": {"function": "bar_of_day", "file": INDICATOR_FILES["session_indicators"]},
    "BARS_REMAINING": {"function": "bars_remaining", "file": INDICATOR_FILES["session_indicators"]},
    "TOTAL_BARS_TODAY": {"function": "total_bars_today", "file": INDICATOR_FILES["session_indicators"]},
    "HAS_NIGHT_SESSION": {"function": "has_night_session", "file": INDICATOR_FILES["session_indicators"]},
    "BAR_OF_SESSION": {"function": "bar_of_session", "file": INDICATOR_FILES["session_indicators"]},
    "BARS_REMAINING_IN_SESSION": {"function": "bars_remaining_in_session", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_BARS_TOTAL": {"function": "session_bars_total", "file": INDICATOR_FILES["session_indicators"]},
    "HOUR_OF_DAY": {"function": "hour_of_day", "file": INDICATOR_FILES["session_indicators"]},
    "MINUTE_OF_HOUR": {"function": "minute_of_hour", "file": INDICATOR_FILES["session_indicators"]},

    # Previous Session Indicators
    "PREV_SESSION_HIGH": {"function": "prev_session_high", "file": INDICATOR_FILES["session_indicators"]},
    "PREV_SESSION_LOW": {"function": "prev_session_low", "file": INDICATOR_FILES["session_indicators"]},
    "PREV_SESSION_CLOSE": {"function": "prev_session_close", "file": INDICATOR_FILES["session_indicators"]},
    "GAP_PCT": {"function": "gap_pct", "file": INDICATOR_FILES["session_indicators"]},

    # Pivot Point Indicators
    "PIVOT": {"function": "pivot", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_R1": {"function": "pivot_r1", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_S1": {"function": "pivot_s1", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_DISTANCE_PCT": {"function": "pivot_distance_pct", "file": INDICATOR_FILES["session_indicators"]},

    # Normalization Indicators (Tier 2 - High IC Potential)
    "BBANDS_PCT_B": {"function": "bbands_pct_b", "file": INDICATOR_FILES["session_indicators"]},
    "BBANDS_BANDWIDTH": {"function": "bbands_bandwidth", "file": INDICATOR_FILES["session_indicators"]},
    "PRICE_ZSCORE": {"function": "price_zscore", "file": INDICATOR_FILES["session_indicators"]},
    "VWAP_ZSCORE": {"function": "vwap_zscore", "file": INDICATOR_FILES["session_indicators"]},

    # Keltner Channel Indicators
    "KC_UPPER": {"function": "kc_upper", "file": INDICATOR_FILES["session_indicators"]},
    "KC_LOWER": {"function": "kc_lower", "file": INDICATOR_FILES["session_indicators"]},
    "KC_PCT_B": {"function": "kc_pct_b", "file": INDICATOR_FILES["session_indicators"]},

    # Chaikin Money Flow
    "CMF": {"function": "cmf", "file": INDICATOR_FILES["session_indicators"]},

    # =========================================================================
    # SECTION 5: INTRADAY CONTEXT INDICATORS (Two-Layer System)
    # =========================================================================

    # Layer 1: SESSION_PHASE - Time-based, deterministic (PRIMARY)
    # Controls WHEN to trade and which strategy to apply
    "SESSION_PHASE": {"function": "session_phase", "file": INDICATOR_FILES["market_context"]},

    # Layer 2: VOLATILITY_STATE - ATR-based, adaptive (SECONDARY)
    # Controls position sizing and stop distances
    # Values: 0=low, 1=normal, 2=high
    "VOLATILITY_STATE": {"function": "volatility_state", "file": INDICATOR_FILES["market_context"]},

    # Combined context calculator (returns DataFrame with all context columns)
    "INTRADAY_CONTEXT": {"function": "calculate_intraday_context", "file": INDICATOR_FILES["market_context"]},
}

# =========================================================================
# Frequency-Scaled Default Parameters
# =========================================================================

def get_intraday_default_params(ctx=None) -> dict:
    """
    Get frequency-scaled default parameters for intraday indicators.

    If ctx (TradingContext) is provided, parameters are scaled to maintain
    consistent lookback periods in real time across different bar sizes.

    Args:
        ctx: TradingContext (if None, falls back to 5m/93 bar defaults)

    Returns:
        Dictionary of indicator parameters
    """
    # Use TradingContext's frequency-scaled parameters
    return ctx.get_indicator_params()


def get_indicator_info(indicator_key: str):
    """Get indicator info by key for intraday."""
    return INTRADAY_INDICATOR_MAPPING.get(indicator_key.upper())


def get_function(indicator_key: str):
    """
    Get the calculator function for an intraday indicator.

    Parameters
    ----------
    indicator_key : str
        Indicator name (e.g., 'RSI', 'VWAP', 'MARKET_REGIME')

    Returns
    -------
    callable
        Function from the appropriate intraday calculator module
    """
    import importlib

    mapping = INTRADAY_INDICATOR_MAPPING.get(indicator_key.upper())
    if not mapping:
        return None

    function_name = mapping["function"]
    file_name = mapping.get("file", INDICATOR_FILES["talib_indicator"])

    # All intraday calculators are in the intraday subdirectory
    module = importlib.import_module(
        f"echolon.indicators.calculators.intraday.{file_name}"
    )

    return getattr(module, function_name, None)


def indicator_exists(indicator_key: str):
    """Check if indicator key exists in intraday mapping."""
    return indicator_key.upper() in INTRADAY_INDICATOR_MAPPING
