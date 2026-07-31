"""
TA-Lib Indicator Utility Functions

This module provides wrapper functions for all 158 TA-Lib indicators.
Each function accepts a DataFrame with OHLCV data and returns the calculated indicator values.

Functions are organized into three categories:
1. Indicators with lookback periods (OHLCV + timeperiod)
2. Indicators without lookback periods (only OHLCV data)
3. Indicators with special parameters (more than OHLCV + timeperiod)
"""

import talib
import numpy as np
import pandas as pd
from typing import Tuple, Union


################################################################################
# SECTION 1: INDICATORS WITH LOOKBACK PERIOD
# These indicators require OHLCV data + timeperiod parameter
################################################################################

# Volatility Indicators
def atr(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Average True Range"""
    atr_values = talib.ATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return atr_values


def natr(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Normalized Average True Range"""
    natr_values = talib.NATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return natr_values


# Momentum Indicators (with simple lookback)
def adx(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Average Directional Movement Index"""
    adx_values = talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return adx_values


def adxr(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Average Directional Movement Index Rating"""
    adxr_values = talib.ADXR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return adxr_values


def aroon(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Aroon"""
    aroon_down, aroon_up = talib.AROON(df['high'].values, df['low'].values, timeperiod=timeperiod)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'UP' in indicator_name:
            return aroon_up
        elif 'DOWN' in indicator_name:
            return aroon_down

    # No indicator_name → return both components as tuple
    return aroon_down, aroon_up


def aroonosc(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Aroon Oscillator"""
    aroon_oscillator = talib.AROONOSC(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return aroon_oscillator


def cci(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Commodity Channel Index"""
    cci_values = talib.CCI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return cci_values


def cmo(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Chande Momentum Oscillator"""
    cmo_values = talib.CMO(df['close'].values, timeperiod=timeperiod)
    return cmo_values


def dx(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Directional Movement Index"""
    dx_values = talib.DX(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return dx_values


def mfi(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Money Flow Index"""
    mfi_values = talib.MFI(df['high'].values, df['low'].values, df['close'].values, df['volume'].values, timeperiod=timeperiod)
    return mfi_values


def minus_di(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Minus Directional Indicator"""
    minus_di_values = talib.MINUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return minus_di_values


def minus_dm(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Minus Directional Movement"""
    minus_dm_values = talib.MINUS_DM(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return minus_dm_values


def mom(df: pd.DataFrame, timeperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Momentum"""
    momentum_values = talib.MOM(df['close'].values, timeperiod=timeperiod)
    return momentum_values


def plus_di(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Plus Directional Indicator"""
    plus_di_values = talib.PLUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return plus_di_values


def plus_dm(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Plus Directional Movement"""
    plus_dm_values = talib.PLUS_DM(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return plus_dm_values


def roc(df: pd.DataFrame, timeperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Rate of change : ((price/prevPrice)-1)*100"""
    roc_values = talib.ROC(df['close'].values, timeperiod=timeperiod)
    return roc_values


def rocp(df: pd.DataFrame, timeperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Rate of change Percentage: (price-prevPrice)/prevPrice"""
    rocp_values = talib.ROCP(df['close'].values, timeperiod=timeperiod)
    return rocp_values


def rocr(df: pd.DataFrame, timeperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Rate of change ratio: (price/prevPrice)"""
    rocr_values = talib.ROCR(df['close'].values, timeperiod=timeperiod)
    return rocr_values


def rocr100(df: pd.DataFrame, timeperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Rate of change ratio 100 scale: (price/prevPrice)*100"""
    rocr100_values = talib.ROCR100(df['close'].values, timeperiod=timeperiod)
    return rocr100_values


def rsi(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Relative Strength Index"""
    rsi_values = talib.RSI(df['close'].values, timeperiod=timeperiod)
    return rsi_values


def trix(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """1-day Rate-Of-Change (ROC) of a Triple Smooth EMA"""
    trix_values = talib.TRIX(df['close'].values, timeperiod=timeperiod)
    return trix_values


def willr(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Williams' %R"""
    willr_values = talib.WILLR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)
    return willr_values


# Overlap Studies (with simple lookback)
def dema(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Double Exponential Moving Average"""
    dema_values = talib.DEMA(df['close'].values, timeperiod=timeperiod)
    return dema_values


def ema(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Exponential Moving Average"""
    ema_values = talib.EMA(df['close'].values, timeperiod=timeperiod)
    return ema_values


def kama(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Kaufman Adaptive Moving Average"""
    kama_values = talib.KAMA(df['close'].values, timeperiod=timeperiod)
    return kama_values


def ma(df: pd.DataFrame, timeperiod: int = 30, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Moving average"""
    ma_values = talib.MA(df['close'].values, timeperiod=timeperiod, matype=matype)
    return ma_values


def midpoint(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """MidPoint over period"""
    midpoint_values = talib.MIDPOINT(df['close'].values, timeperiod=timeperiod)
    return midpoint_values


def midprice(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Midpoint Price over period"""
    midprice_values = talib.MIDPRICE(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return midprice_values


def sma(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Simple Moving Average"""
    sma_values = talib.SMA(df['close'].values, timeperiod=timeperiod)
    return sma_values


def tema(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Triple Exponential Moving Average"""
    tema_values = talib.TEMA(df['close'].values, timeperiod=timeperiod)
    return tema_values


def trima(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Triangular Moving Average"""
    trima_values = talib.TRIMA(df['close'].values, timeperiod=timeperiod)
    return trima_values


def wma(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Weighted Moving Average"""
    wma_values = talib.WMA(df['close'].values, timeperiod=timeperiod)
    return wma_values


# Math Operators (with lookback)
def max_func(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Highest value over a specified period"""
    max_values = talib.MAX(df['close'].values, timeperiod=timeperiod)
    return max_values


def maxindex(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Index of highest value over a specified period"""
    max_indices = talib.MAXINDEX(df['close'].values, timeperiod=timeperiod)
    return max_indices


def min_func(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Lowest value over a specified period"""
    min_values = talib.MIN(df['close'].values, timeperiod=timeperiod)
    return min_values


def highest_high(df: pd.DataFrame, timeperiod: int = 20, indicator_name: str = None) -> np.ndarray:
    """Donchian channel upper — highest of HIGH prices over N periods.

    Distinct from ``max_func`` (which uses CLOSE). Use this for breakout
    strategies where the upper boundary is the rolling maximum of the
    high series, not the close series.
    """
    return talib.MAX(df['high'].values, timeperiod=timeperiod)


def lowest_low(df: pd.DataFrame, timeperiod: int = 20, indicator_name: str = None) -> np.ndarray:
    """Donchian channel lower — lowest of LOW prices over N periods.

    Distinct from ``min_func`` (which uses CLOSE). Use this for breakout
    strategies where the lower boundary is the rolling minimum of the
    low series, not the close series.
    """
    return talib.MIN(df['low'].values, timeperiod=timeperiod)


def minindex(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Index of lowest value over a specified period"""
    min_indices = talib.MININDEX(df['close'].values, timeperiod=timeperiod)
    return min_indices


def minmax(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Lowest and highest values over a specified period"""
    min_values, max_values = talib.MINMAX(df['close'].values, timeperiod=timeperiod)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'MIN' in indicator_name:
            return min_values
        elif 'MAX' in indicator_name:
            return max_values

    # No indicator_name → return both components as tuple
    return min_values, max_values


def minmaxindex(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Indexes of lowest and highest values over a specified period"""
    min_indices, max_indices = talib.MINMAXINDEX(df['close'].values, timeperiod=timeperiod)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'MIN' in indicator_name:
            return min_indices
        elif 'MAX' in indicator_name:
            return max_indices

    # No indicator_name → return both components as tuple
    return min_indices, max_indices


def sum_func(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Summation"""
    sum_values = talib.SUM(df['close'].values, timeperiod=timeperiod)
    return sum_values


# Statistic Functions (with lookback)
def beta(df: pd.DataFrame, timeperiod: int = 5, indicator_name: str = None) -> np.ndarray:
    """Beta"""
    beta_values = talib.BETA(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return beta_values


def correl(df: pd.DataFrame, timeperiod: int = 30, indicator_name: str = None) -> np.ndarray:
    """Pearson's Correlation Coefficient (r)"""
    correlation = talib.CORREL(df['high'].values, df['low'].values, timeperiod=timeperiod)
    return correlation


def linearreg(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Linear Regression"""
    linear_regression = talib.LINEARREG(df['close'].values, timeperiod=timeperiod)
    return linear_regression


def linearreg_angle(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Angle"""
    lr_angle = talib.LINEARREG_ANGLE(df['close'].values, timeperiod=timeperiod)
    return lr_angle


def linearreg_intercept(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Intercept"""
    lr_intercept = talib.LINEARREG_INTERCEPT(df['close'].values, timeperiod=timeperiod)
    return lr_intercept


def linearreg_slope(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Slope"""
    lr_slope = talib.LINEARREG_SLOPE(df['close'].values, timeperiod=timeperiod)
    return lr_slope


def tsf(df: pd.DataFrame, timeperiod: int = 14, indicator_name: str = None) -> np.ndarray:
    """Time Series Forecast"""
    time_series_forecast = talib.TSF(df['close'].values, timeperiod=timeperiod)
    return time_series_forecast


################################################################################
# SECTION 2: INDICATORS WITHOUT LOOKBACK PERIOD
# These indicators only require OHLCV data (any combination)
################################################################################

# Momentum Indicators (without lookback)
def bop(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Balance Of Power"""
    bop_values = talib.BOP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return bop_values


# Math Operators (without lookback)
def add(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Add"""
    result = talib.ADD(df['high'].values, df['low'].values)
    return result


def div(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Div"""
    result = talib.DIV(df['high'].values, df['low'].values)
    return result


def mult(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Mult"""
    result = talib.MULT(df['high'].values, df['low'].values)
    return result


def sub(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Subtraction"""
    result = talib.SUB(df['high'].values, df['low'].values)
    return result


# Math Transform (without lookback)
def acos(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ACos"""
    result = talib.ACOS(df['close'].values)
    return result


def asin(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ASin"""
    result = talib.ASIN(df['close'].values)
    return result


def atan(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ATan"""
    result = talib.ATAN(df['close'].values)
    return result


def ceil(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Ceil"""
    result = talib.CEIL(df['close'].values)
    return result


def cos(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Cos"""
    result = talib.COS(df['close'].values)
    return result




def floor(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Floor"""
    result = talib.FLOOR(df['close'].values)
    return result


def ln(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Log Natural"""
    result = talib.LN(df['close'].values)
    return result


def log10(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Log10"""
    result = talib.LOG10(df['close'].values)
    return result


def sin(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Sin"""
    result = talib.SIN(df['close'].values)
    return result




def sqrt(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Square Root"""
    result = talib.SQRT(df['close'].values)
    return result


def tan(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Tan"""
    result = talib.TAN(df['close'].values)
    return result


def tanh(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Tanh"""
    result = talib.TANH(df['close'].values)
    return result


# Price Transform (without lookback)
def avgprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Average Price"""
    avg_price = talib.AVGPRICE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return avg_price


def medprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Median Price"""
    median_price = talib.MEDPRICE(df['high'].values, df['low'].values)
    return median_price


def typprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Typical Price"""
    typical_price = talib.TYPPRICE(df['high'].values, df['low'].values, df['close'].values)
    return typical_price


def wclprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Weighted Close Price"""
    weighted_close = talib.WCLPRICE(df['high'].values, df['low'].values, df['close'].values)
    return weighted_close


# Volatility Indicators (without lookback)
def trange(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """True Range"""
    true_range = talib.TRANGE(df['high'].values, df['low'].values, df['close'].values)
    return true_range


# Volume Indicators (without lookback)
def ad(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Chaikin A/D Line"""
    ad_line = talib.AD(df['high'].values, df['low'].values, df['close'].values, df['volume'].values)
    return ad_line


def obv(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """On Balance Volume"""
    obv_values = talib.OBV(df['close'].values, df['volume'].values)
    return obv_values


# Scale-invariant volume indicators (rolling z-score of a cumulative line).
# These HAVE a lookback (``period``) — they are the pre-computed, per-contract
# normalization of obv/ad. Prefer them over computing a rolling z-score at
# runtime via ``get_indicator_series('obv', N)``: the runtime form raises
# IndexError on a backtest window shorter than N (e.g. a one-year WFA OOS slice)
# and silently reads future bars (lookahead) on longer windows. Computed per
# contract, so the window never spans a contract rollover.
def _rolling_zscore(series: pd.Series, period: int) -> np.ndarray:
    """Rolling z-score of a series: (x - rollmean) / rollstd.

    Warmup (first ``period - 1`` bars, insufficient history) -> NaN, the honest
    "not yet computable" marker (matches the TA-Lib lookback convention; the
    No-Misleading-Fallback policy forbids a fabricated 0 here). A degenerate full
    window with zero dispersion (std == 0) -> 0.0 (value exactly at its mean).
    """
    mean = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    zscore = (series - mean) / std
    # std == 0 -> 0.0 (the 0/0 above is NaN); warmup (std is NaN) stays NaN.
    return zscore.where(std != 0, 0.0).to_numpy()


def obv_zscore(df: pd.DataFrame, period: int = 20, indicator_name: str = None) -> np.ndarray:
    """Scale-invariant On Balance Volume — rolling z-score of OBV.

    OBV is cumulative and scale-dependent, so a raw threshold is not portable
    across contracts/price levels; the rolling z-score is. See the section
    comment above for why this is preferred over a runtime rolling computation.
    """
    obv_series = pd.Series(
        talib.OBV(df['close'].values, df['volume'].values), index=df.index,
    )
    return _rolling_zscore(obv_series, period)


def ad_zscore(df: pd.DataFrame, period: int = 20, indicator_name: str = None) -> np.ndarray:
    """Scale-invariant Chaikin A/D Line — rolling z-score of AD.

    Same rationale as :func:`obv_zscore`: AD is cumulative/scale-dependent, so
    the rolling z-score gives a portable, thresholdable signal. Per contract.
    """
    ad_series = pd.Series(
        talib.AD(df['high'].values, df['low'].values,
                 df['close'].values, df['volume'].values), index=df.index,
    )
    return _rolling_zscore(ad_series, period)


# Pattern Recognition Functions (without lookback)
def cdl2crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Two Crows"""
    pattern = talib.CDL2CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3blackcrows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three Black Crows"""
    pattern = talib.CDL3BLACKCROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3inside(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three Inside Up/Down"""
    pattern = talib.CDL3INSIDE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3linestrike(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three-Line Strike"""
    pattern = talib.CDL3LINESTRIKE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3outside(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three Outside Up/Down"""
    pattern = talib.CDL3OUTSIDE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3starsinsouth(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three Stars In The South"""
    pattern = talib.CDL3STARSINSOUTH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdl3whitesoldiers(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Three Advancing White Soldiers"""
    pattern = talib.CDL3WHITESOLDIERS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdladvanceblock(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Advance Block"""
    pattern = talib.CDLADVANCEBLOCK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlbelthold(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Belt-hold"""
    pattern = talib.CDLBELTHOLD(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlbreakaway(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Breakaway"""
    pattern = talib.CDLBREAKAWAY(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlclosingmarubozu(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Closing Marubozu"""
    pattern = talib.CDLCLOSINGMARUBOZU(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlconcealbabyswall(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Concealing Baby Swallow"""
    pattern = talib.CDLCONCEALBABYSWALL(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlcounterattack(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Counterattack"""
    pattern = talib.CDLCOUNTERATTACK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdldoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Doji"""
    pattern = talib.CDLDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdldojistar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Doji Star"""
    pattern = talib.CDLDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdldragonflydoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Dragonfly Doji"""
    pattern = talib.CDLDRAGONFLYDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlengulfing(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Engulfing Pattern"""
    pattern = talib.CDLENGULFING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlgapsidesidewhite(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Up/Down-gap side-by-side white lines"""
    pattern = talib.CDLGAPSIDESIDEWHITE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlgravestonedoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Gravestone Doji"""
    pattern = talib.CDLGRAVESTONEDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhammer(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hammer"""
    pattern = talib.CDLHAMMER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhangingman(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hanging Man"""
    pattern = talib.CDLHANGINGMAN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlharami(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Harami Pattern"""
    pattern = talib.CDLHARAMI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlharamicross(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Harami Cross Pattern"""
    pattern = talib.CDLHARAMICROSS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhighwave(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """High-Wave Candle"""
    pattern = talib.CDLHIGHWAVE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhikkake(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hikkake Pattern"""
    pattern = talib.CDLHIKKAKE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhikkakemod(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Modified Hikkake Pattern"""
    pattern = talib.CDLHIKKAKEMOD(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlhomingpigeon(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Homing Pigeon"""
    pattern = talib.CDLHOMINGPIGEON(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlidentical3crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Identical Three Crows"""
    pattern = talib.CDLIDENTICAL3CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlinneck(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """In-Neck Pattern"""
    pattern = talib.CDLINNECK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlinvertedhammer(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Inverted Hammer"""
    pattern = talib.CDLINVERTEDHAMMER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlkicking(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Kicking"""
    pattern = talib.CDLKICKING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlkickingbylength(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Kicking - bull/bear determined by the longer marubozu"""
    pattern = talib.CDLKICKINGBYLENGTH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlladderbottom(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Ladder Bottom"""
    pattern = talib.CDLLADDERBOTTOM(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdllongleggeddoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Long Legged Doji"""
    pattern = talib.CDLLONGLEGGEDDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdllongline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Long Line Candle"""
    pattern = talib.CDLLONGLINE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlmarubozu(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Marubozu"""
    pattern = talib.CDLMARUBOZU(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlmatchinglow(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Matching Low"""
    pattern = talib.CDLMATCHINGLOW(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlonneck(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """On-Neck Pattern"""
    pattern = talib.CDLONNECK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlpiercing(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Piercing Pattern"""
    pattern = talib.CDLPIERCING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlrickshawman(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Rickshaw Man"""
    pattern = talib.CDLRICKSHAWMAN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlrisefall3methods(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Rising/Falling Three Methods"""
    pattern = talib.CDLRISEFALL3METHODS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlseparatinglines(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Separating Lines"""
    pattern = talib.CDLSEPARATINGLINES(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlshootingstar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Shooting Star"""
    pattern = talib.CDLSHOOTINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlshortline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Short Line Candle"""
    pattern = talib.CDLSHORTLINE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlspinningtop(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Spinning Top"""
    pattern = talib.CDLSPINNINGTOP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlstalledpattern(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Stalled Pattern"""
    pattern = talib.CDLSTALLEDPATTERN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlsticksandwich(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Stick Sandwich"""
    pattern = talib.CDLSTICKSANDWICH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdltakuri(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Takuri (Dragonfly Doji with very long lower shadow)"""
    pattern = talib.CDLTAKURI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdltasukigap(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Tasuki Gap"""
    pattern = talib.CDLTASUKIGAP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlthrusting(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Thrusting Pattern"""
    pattern = talib.CDLTHRUSTING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdltristar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Tristar Pattern"""
    pattern = talib.CDLTRISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlunique3river(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Unique 3 River"""
    pattern = talib.CDLUNIQUE3RIVER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlupsidegap2crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Upside Gap Two Crows"""
    pattern = talib.CDLUPSIDEGAP2CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


def cdlxsidegap3methods(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Upside/Downside Gap Three Methods"""
    pattern = talib.CDLXSIDEGAP3METHODS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)
    return pattern


# Cycle Indicators (without lookback)
def ht_dcperiod(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Dominant Cycle Period"""
    dominant_cycle_period = talib.HT_DCPERIOD(df['close'].values)
    return dominant_cycle_period


def ht_dcphase(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Dominant Cycle Phase"""
    dominant_cycle_phase = talib.HT_DCPHASE(df['close'].values)
    return dominant_cycle_phase


def ht_phasor(df: pd.DataFrame, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Hilbert Transform - Phasor Components"""
    inphase, quadrature = talib.HT_PHASOR(df['close'].values)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'INPHASE' in indicator_name:
            return inphase
        elif 'QUADRATURE' in indicator_name:
            return quadrature

    # No indicator_name → return both components as tuple
    return inphase, quadrature


def ht_sine(df: pd.DataFrame, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Hilbert Transform - SineWave"""
    sine, leadsine = talib.HT_SINE(df['close'].values)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LEADSINE' in indicator_name:
            return leadsine
        elif 'SINE' in indicator_name or 'HT_SINE' in indicator_name:
            return sine

    # No indicator_name → return both components as tuple
    return sine, leadsine


def ht_trendmode(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Trend vs Cycle Mode"""
    trend_mode = talib.HT_TRENDMODE(df['close'].values)
    return trend_mode


def ht_trendline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Instantaneous Trendline"""
    trendline = talib.HT_TRENDLINE(df['close'].values)
    return trendline


################################################################################
# SECTION 3: INDICATORS WITH SPECIAL PARAMETERS
# These indicators require more than OHLCV + timeperiod
################################################################################

# Momentum Indicators (with special parameters)
def apo(df: pd.DataFrame, fastperiod: int = 12, slowperiod: int = 26, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Absolute Price Oscillator"""
    apo_values = talib.APO(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, matype=matype)
    return apo_values


def ppo(df: pd.DataFrame, fastperiod: int = 12, slowperiod: int = 26, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Percentage Price Oscillator"""
    ppo_values = talib.PPO(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, matype=matype)
    return ppo_values


def macd(df: pd.DataFrame, fastperiod: int = 12, slowperiod: int = 26, signalperiod: int = 9, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Moving Average Convergence/Divergence"""
    macd_line, macd_signal, macd_histogram = talib.MACD(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram

    # No indicator_name → return both components as tuple
    return macd_line, macd_signal, macd_histogram


def macdext(df: pd.DataFrame, fastperiod: int = 12, fastmatype: int = 0, slowperiod: int = 26,
           slowmatype: int = 0, signalperiod: int = 9, signalmatype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """MACD with controllable MA type"""
    macd_line, macd_signal, macd_histogram = talib.MACDEXT(df['close'].values, fastperiod=fastperiod, fastmatype=fastmatype,
                                                           slowperiod=slowperiod, slowmatype=slowmatype,
                                                           signalperiod=signalperiod, signalmatype=signalmatype)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram

    # No indicator_name → return both components as tuple
    return macd_line, macd_signal, macd_histogram


def macdfix(df: pd.DataFrame, signalperiod: int = 9, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Moving Average Convergence/Divergence Fix 12/26"""
    macd_line, macd_signal, macd_histogram = talib.MACDFIX(df['close'].values, signalperiod=signalperiod)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram

    # No indicator_name → return both components as tuple
    return macd_line, macd_signal, macd_histogram


def ultosc(df: pd.DataFrame, timeperiod1: int = 7,
          timeperiod2: int = 14, timeperiod3: int = 28, indicator_name: str = None) -> np.ndarray:
    """Ultimate Oscillator"""
    ultosc_values = talib.ULTOSC(df['high'].values, df['low'].values, df['close'].values, timeperiod1=timeperiod1, timeperiod2=timeperiod2, timeperiod3=timeperiod3)
    return ultosc_values


def stoch(df: pd.DataFrame, fastk_period: int = 5,
         slowk_period: int = 3, slowk_matype: int = 0, slowd_period: int = 3, slowd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic"""
    slowk, slowd = talib.STOCH(df['high'].values, df['low'].values, df['close'].values, fastk_period=fastk_period, slowk_period=slowk_period,
                               slowk_matype=slowk_matype, slowd_period=slowd_period, slowd_matype=slowd_matype)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'SLOWK' in indicator_name:
            return slowk
        elif 'SLOWD' in indicator_name:
            return slowd

    # No indicator_name → return both components as tuple
    return slowk, slowd


def stochf(df: pd.DataFrame, fastk_period: int = 5,
          fastd_period: int = 3, fastd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic Fast"""
    fastk, fastd = talib.STOCHF(df['high'].values, df['low'].values, df['close'].values, fastk_period=fastk_period, fastd_period=fastd_period, fastd_matype=fastd_matype)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FASTK' in indicator_name:
            return fastk
        elif 'FASTD' in indicator_name:
            return fastd

    # No indicator_name → return both components as tuple
    return fastk, fastd


def stochrsi(df: pd.DataFrame, timeperiod: int = 14, fastk_period: int = 5,
            fastd_period: int = 3, fastd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic Relative Strength Index"""
    fastk, fastd = talib.STOCHRSI(df['close'].values, timeperiod=timeperiod, fastk_period=fastk_period,
                                  fastd_period=fastd_period, fastd_matype=fastd_matype)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FASTK' in indicator_name:
            return fastk
        elif 'FASTD' in indicator_name:
            return fastd

    # No indicator_name → return both components as tuple
    return fastk, fastd


# Overlap Studies (with special parameters)
def bbands(df: pd.DataFrame, timeperiod: int = 5, nbdevup: float = 2, nbdevdn: float = 2, matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Bollinger Bands"""
    upper_band, middle_band, lower_band = talib.BBANDS(df['close'].values, timeperiod=timeperiod, nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'UPPER' in indicator_name:
            return upper_band
        elif 'MIDDLE' in indicator_name:
            return middle_band
        elif 'LOWER' in indicator_name:
            return lower_band

    # No indicator_name → return both components as tuple
    return upper_band, middle_band, lower_band


def bbands_pct_b(df: pd.DataFrame, timeperiod: int = 20, nbdevup: float = 2, nbdevdn: float = 2, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Bollinger %B - normalized position within Bollinger Bands (0-1 scale).
    %B < 0: below lower band, %B = 0.5: at middle, %B > 1: above upper band."""
    upper, middle, lower = talib.BBANDS(df['close'].values, timeperiod=timeperiod, nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype)
    band_width = upper - lower
    pct_b = np.where(band_width > 0, (df['close'].values - lower) / band_width, 0.5)
    return pct_b


def bbands_bandwidth(df: pd.DataFrame, timeperiod: int = 20, nbdevup: float = 2, nbdevdn: float = 2, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Bollinger Bandwidth - band width as percentage of middle band.
    Low bandwidth = volatility squeeze (potential breakout). High bandwidth = high volatility."""
    upper, middle, lower = talib.BBANDS(df['close'].values, timeperiod=timeperiod, nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype)
    bandwidth = np.where(middle > 0, (upper - lower) / middle * 100, 0)
    return bandwidth


def mama(df: pd.DataFrame, fastlimit: float = 0.5, slowlimit: float = 0.05, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """MESA Adaptive Moving Average"""
    mama_values, fama_values = talib.MAMA(df['close'].values, fastlimit=fastlimit, slowlimit=slowlimit)

    # Return specific component based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FAMA' in indicator_name:
            return fama_values
        elif 'MAMA' in indicator_name:
            return mama_values

    # No indicator_name → return both components as tuple
    return mama_values, fama_values


def mavp(df: pd.DataFrame, periods: np.ndarray = None, minperiod: int = 2, maxperiod: int = 30, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Moving average with variable period"""
    # If periods not provided, use a default array of 30-period for all data points
    if periods is None:
        periods = np.full(len(df), 30, dtype=np.float64)

    mavp_values = talib.MAVP(df['close'].values, periods, minperiod=minperiod, maxperiod=maxperiod, matype=matype)
    return mavp_values


def sar(df: pd.DataFrame, acceleration: float = 0.02, maximum: float = 0.2, indicator_name: str = None) -> np.ndarray:
    """Parabolic SAR"""
    sar_values = talib.SAR(df['high'].values, df['low'].values, acceleration=acceleration, maximum=maximum)
    return sar_values


def sarext(df: pd.DataFrame, startvalue: float = 0, offsetonreverse: float = 0,
          accelerationinitlong: float = 0.02, accelerationlong: float = 0.02, accelerationmaxlong: float = 0.2,
          accelerationinitshort: float = 0.02, accelerationshort: float = 0.02, accelerationmaxshort: float = 0.2, indicator_name: str = None) -> np.ndarray:
    """Parabolic SAR - Extended"""
    sarext_values = talib.SAREXT(df['high'].values, df['low'].values, startvalue=startvalue, offsetonreverse=offsetonreverse,
                                 accelerationinitlong=accelerationinitlong, accelerationlong=accelerationlong,
                                 accelerationmaxlong=accelerationmaxlong, accelerationinitshort=accelerationinitshort,
                                 accelerationshort=accelerationshort, accelerationmaxshort=accelerationmaxshort)
    return sarext_values


def t3(df: pd.DataFrame, timeperiod: int = 5, vfactor: float = 0, indicator_name: str = None) -> np.ndarray:
    """Triple Exponential Moving Average (T3)"""
    t3_values = talib.T3(df['close'].values, timeperiod=timeperiod, vfactor=vfactor)
    return t3_values


# Volume Indicators (with special parameters)
# Statistic Functions (with special parameters)
def stddev(df: pd.DataFrame, timeperiod: int = 5, nbdev: float = 1, indicator_name: str = None) -> np.ndarray:
    """Standard Deviation"""
    std_deviation = talib.STDDEV(df['close'].values, timeperiod=timeperiod, nbdev=nbdev)
    return std_deviation


def var(df: pd.DataFrame, timeperiod: int = 5, nbdev: float = 1, indicator_name: str = None) -> np.ndarray:
    """Variance"""
    variance = talib.VAR(df['close'].values, timeperiod=timeperiod, nbdev=nbdev)
    return variance


# Pattern Recognition Functions (with special parameters)
def cdlabandonedbaby(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    """Abandoned Baby"""
    pattern = talib.CDLABANDONEDBABY(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdldarkcloudcover(df: pd.DataFrame, penetration: float = 0.5, indicator_name: str = None) -> np.ndarray:
    """Dark Cloud Cover"""
    pattern = talib.CDLDARKCLOUDCOVER(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdleveningdojistar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    """Evening Doji Star"""
    pattern = talib.CDLEVENINGDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdleveningstar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    """Evening Star"""
    pattern = talib.CDLEVENINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdlmathold(df: pd.DataFrame, penetration: float = 0.5, indicator_name: str = None) -> np.ndarray:
    """Mat Hold"""
    pattern = talib.CDLMATHOLD(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdlmorningdojistar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    """Morning Doji Star"""
    pattern = talib.CDLMORNINGDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


def cdlmorningstar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    """Morning Star"""
    pattern = talib.CDLMORNINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)
    return pattern


# Volume Indicators (with special parameters)
def adosc(df: pd.DataFrame, fastperiod: int = 3, slowperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Chaikin A/D Oscillator"""
    ad_oscillator = talib.ADOSC(df['high'].values, df['low'].values, df['close'].values, df['volume'].values, fastperiod=fastperiod, slowperiod=slowperiod)
    return ad_oscillator
