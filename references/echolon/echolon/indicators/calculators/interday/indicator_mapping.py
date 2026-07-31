"""
Per-contract TA-Lib calculator map (canonical name: ``PER_CONTRACT_TALIB_MAP``).

Maps single-contract, TA-Lib-style indicator keys to their calculator function
+ module. These are dispatched in the PER-CONTRACT indicator loop
(``processor._compute_indicators_for_contract`` → ``function(df, **params)``).

This is NOT the catalog / availability surface — that is
``echolon.indicators.catalog`` (the union of this map, the regime-classifier
registry, and the curve/carry registry). Curve indicators (carry) and regime
classifiers are intentionally absent here (different call contracts).

``INDICATOR_MAPPING`` remains as a deprecated alias (see bottom of module).
"""

INDICATOR_FILES = {
    "talib_indicator": "ta_lib",
}

# Indicator key to function name + file mapping
PER_CONTRACT_TALIB_MAP = {
    # Indicators with lookback period
    "ATR": {"function": "atr",
            "file": INDICATOR_FILES["talib_indicator"]},
    "ADX": {"function": "adx",
           "file": INDICATOR_FILES["talib_indicator"]},
    "ADXR": {"function": "adxr",
            "file": INDICATOR_FILES["talib_indicator"]},
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
    # Scale-invariant (rolling z-score) volume indicators — pre-computed
    # normalization of OBV/AD; have a ``period`` lookback. See ta_lib.obv_zscore.
    "OBV_ZSCORE": {"function": "obv_zscore", "file": INDICATOR_FILES["talib_indicator"]},
    "AD_ZSCORE": {"function": "ad_zscore", "file": INDICATOR_FILES["talib_indicator"]},
    "WILLR": {"function": "willr", "file": INDICATOR_FILES["talib_indicator"]},
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
    "MAX": {"function": "max_func", "file": INDICATOR_FILES["talib_indicator"]},
    "MAXINDEX": {"function": "maxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MIN": {"function": "min_func", "file": INDICATOR_FILES["talib_indicator"]},
    "MININDEX": {"function": "minindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MIN": {"function": "minmax", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MAX": {"function": "minmax", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MIN": {"function": "minmaxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MAX": {"function": "minmaxindex", "file": INDICATOR_FILES["talib_indicator"]},
    "SUM": {"function": "sum_func", "file": INDICATOR_FILES["talib_indicator"]},
    "BETA": {"function": "beta", "file": INDICATOR_FILES["talib_indicator"]},
    "CORREL": {"function": "correl", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG": {"function": "linearreg", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_ANGLE": {"function": "linearreg_angle", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_INTERCEPT": {"function": "linearreg_intercept", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_SLOPE": {"function": "linearreg_slope", "file": INDICATOR_FILES["talib_indicator"]},
    "TSF": {"function": "tsf", "file": INDICATOR_FILES["talib_indicator"]},
    "NATR": {"function": "natr", "file": INDICATOR_FILES["talib_indicator"]},
    "HIGHEST_HIGH": {"function": "highest_high", "file": INDICATOR_FILES["talib_indicator"]},
    "LOWEST_LOW": {"function": "lowest_low", "file": INDICATOR_FILES["talib_indicator"]},

    # Indicators without lookback period
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
    "CDL2CROWS": {"function": "cdl2crows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3BLACKCROWS": {"function": "cdl3blackcrows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3INSIDE": {"function": "cdl3inside", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3LINESTRIKE": {"function": "cdl3linestrike", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3OUTSIDE": {"function": "cdl3outside", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3STARSINSOUTH": {"function": "cdl3starsinsouth", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3WHITESOLDIERS": {"function": "cdl3whitesoldiers", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLADVANCEBLOCK": {"function": "cdladvanceblock", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLBELTHOLD": {"function": "cdlbelthold", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLBREAKAWAY": {"function": "cdlbreakaway", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCLOSINGMARUBOZU": {"function": "cdlclosingmarubozu", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCONCEALBABYSWALL": {"function": "cdlconcealbabyswall", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCOUNTERATTACK": {"function": "cdlcounterattack", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJI": {"function": "cdldoji", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJISTAR": {"function": "cdldojistar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDRAGONFLYDOJI": {"function": "cdldragonflydoji", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLENGULFING": {"function": "cdlengulfing", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLGAPSIDESIDEWHITE": {"function": "cdlgapsidesidewhite", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLGRAVESTONEDOJI": {"function": "cdlgravestonedoji", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHAMMER": {"function": "cdlhammer", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHANGINGMAN": {"function": "cdlhangingman", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMI": {"function": "cdlharami", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMICROSS": {"function": "cdlharamicross", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIGHWAVE": {"function": "cdlhighwave", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIKKAKE": {"function": "cdlhikkake", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIKKAKEMOD": {"function": "cdlhikkakemod", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHOMINGPIGEON": {"function": "cdlhomingpigeon", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLIDENTICAL3CROWS": {"function": "cdlidentical3crows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLINNECK": {"function": "cdlinneck", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLINVERTEDHAMMER": {"function": "cdlinvertedhammer", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLKICKING": {"function": "cdlkicking", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLKICKINGBYLENGTH": {"function": "cdlkickingbylength", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLADDERBOTTOM": {"function": "cdlladderbottom", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLONGLEGGEDDOJI": {"function": "cdllongleggeddoji", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLONGLINE": {"function": "cdllongline", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMARUBOZU": {"function": "cdlmarubozu", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMATCHINGLOW": {"function": "cdlmatchinglow", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLONNECK": {"function": "cdlonneck", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLPIERCING": {"function": "cdlpiercing", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLRICKSHAWMAN": {"function": "cdlrickshawman", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLRISEFALL3METHODS": {"function": "cdlrisefall3methods", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSEPARATINGLINES": {"function": "cdlseparatinglines", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHOOTINGSTAR": {"function": "cdlshootingstar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHORTLINE": {"function": "cdlshortline", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSPINNINGTOP": {"function": "cdlspinningtop", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSTALLEDPATTERN": {"function": "cdlstalledpattern", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSTICKSANDWICH": {"function": "cdlsticksandwich", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTAKURI": {"function": "cdltakuri", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTASUKIGAP": {"function": "cdltasukigap", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTHRUSTING": {"function": "cdlthrusting", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTRISTAR": {"function": "cdltristar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLUNIQUE3RIVER": {"function": "cdlunique3river", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLUPSIDEGAP2CROWS": {"function": "cdlupsidegap2crows", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLXSIDEGAP3METHODS": {"function": "cdlxsidegap3methods", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPERIOD": {"function": "ht_dcperiod", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPHASE": {"function": "ht_dcphase", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_INPHASE": {"function": "ht_phasor", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_QUADRATURE": {"function": "ht_phasor", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_SINE": {"function": "ht_sine", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_LEADSINE": {"function": "ht_sine", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDMODE": {"function": "ht_trendmode", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDLINE": {"function": "ht_trendline", "file": INDICATOR_FILES["talib_indicator"]},

    # Indicators with special parameters
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
    "BBANDS_PCT_B": {"function": "bbands_pct_b", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_BANDWIDTH": {"function": "bbands_bandwidth", "file": INDICATOR_FILES["talib_indicator"]},
    "MAMA": {"function": "mama", "file": INDICATOR_FILES["talib_indicator"]},
    "FAMA": {"function": "mama", "file": INDICATOR_FILES["talib_indicator"]},
    "MAVP": {"function": "mavp", "file": INDICATOR_FILES["talib_indicator"]},
    "SAR": {"function": "sar", "file": INDICATOR_FILES["talib_indicator"]},
    "SAREXT": {"function": "sarext", "file": INDICATOR_FILES["talib_indicator"]},
    "T3": {"function": "t3", "file": INDICATOR_FILES["talib_indicator"]},
    "STDDEV": {"function": "stddev", "file": INDICATOR_FILES["talib_indicator"]},
    "VAR": {"function": "var", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLABANDONEDBABY": {"function": "cdlabandonedbaby", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDARKCLOUDCOVER": {"function": "cdldarkcloudcover", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLEVENINGDOJISTAR": {"function": "cdleveningdojistar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLEVENINGSTAR": {"function": "cdleveningstar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMATHOLD": {"function": "cdlmathold", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMORNINGDOJISTAR": {"function": "cdlmorningdojistar", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMORNINGSTAR": {"function": "cdlmorningstar", "file": INDICATOR_FILES["talib_indicator"]},
    "ADOSC": {"function": "adosc", "file": INDICATOR_FILES["talib_indicator"]}
}

# Deprecated alias — kept so any straggler / dynamic importer of the old name
# keeps working. Prefer PER_CONTRACT_TALIB_MAP. Remove once all callers migrate.
INDICATOR_MAPPING = PER_CONTRACT_TALIB_MAP


# Function to get all available indicator keys
def get_all_indicator_keys():
    """Return list of all available indicator keys"""
    return list(PER_CONTRACT_TALIB_MAP.keys())

# Function to get the actual function by indicator key
def get_function(indicator_key, frequency: str = "day"):
    """
    Get the actual indicator function by indicator key.

    Routes to appropriate calculator based on frequency:
    - Interday (day/daily): Uses interday calculators with interday mapping
    - Intraday (minute): Uses intraday calculators with intraday mapping

    Args:
        indicator_key: Indicator name (e.g., 'RSI', 'MACD_LINE', 'VWAP')
        frequency: Data frequency ('day' for interday, 'minute' for intraday)

    Returns:
        Function from the appropriate calculator module
    """
    import importlib

    # Route to intraday-specific mapping for intraday frequencies
    if frequency in ("minute", "intraday"):
        from . import intraday_indicator_mapping
        return intraday_indicator_mapping.get_function(indicator_key)

    # Use interday mapping (default)
    mapping = PER_CONTRACT_TALIB_MAP.get(indicator_key.upper())
    if not mapping:
        return None

    function_name = mapping["function"]
    file_name = mapping.get("file", INDICATOR_FILES["talib_indicator"])

    # Import from interday calculators
    module = importlib.import_module(
        f"echolon.indicators.calculators.interday.{file_name}"
    )

    # Get the function from the module
    return getattr(module, function_name, None)

def get_indicator_info(indicator_key, frequency: str = "day"):
    """Get function + file metadata by indicator key.

    Args:
        indicator_key: Indicator name (e.g., 'RSI', 'VWAP')
        frequency: Data frequency ('day' for interday, 'minute' for intraday)

    Returns:
        Dict with 'function' and 'file' keys.
    """
    # Route to intraday mapping for intraday frequencies
    if frequency in ("minute", "intraday"):
        from . import intraday_indicator_mapping
        return intraday_indicator_mapping.get_indicator_info(indicator_key)

    # Use interday mapping (default)
    return PER_CONTRACT_TALIB_MAP.get(indicator_key.upper())

# Function to check if indicator exists
def indicator_exists(indicator_key):
    """Check if indicator key exists in mapping"""
    return indicator_key.upper() in PER_CONTRACT_TALIB_MAP