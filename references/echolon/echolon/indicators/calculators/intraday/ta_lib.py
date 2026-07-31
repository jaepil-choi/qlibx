"""
Intraday Technical Indicators (TA-Lib)
======================================

Technical indicators recalibrated for intraday (5-min/15-min) bars.
Period scaling based on INTRADAY_INDICATOR_MIGRATION_GUIDE.md.

Key differences from interday:
- Shorter periods (scaled for 93 bars/day)
- More responsive to price changes
- Session-aware calculations where relevant

Intraday Default Periods:
- 28 bars ≈ 2.3 hours (common default for momentum/trend)
- 40 bars ≈ 3.3 hours (extended periods)
- 12 bars ≈ 1 hour (fast MA)
- 93 bars ≈ 1 trading day
"""

import pandas as pd
import numpy as np
import talib
from typing import Dict, Any, Tuple, Union
import logging

logger = logging.getLogger(__name__)


################################################################################
# SECTION 1: INDICATORS WITH LOOKBACK PERIOD (Intraday Defaults)
################################################################################

# Volatility Indicators
def atr(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Average True Range (intraday: 28 bars ≈ 2.3 hours)"""
    return talib.ATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def natr(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Normalized Average True Range (intraday: 28 bars)"""
    return talib.NATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


# Momentum Indicators
def adx(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Average Directional Movement Index (intraday: 28 bars)"""
    return talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def adxr(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Average Directional Movement Index Rating (intraday: 28 bars)"""
    return talib.ADXR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def aroon(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Aroon (intraday: 40 bars ≈ 3.3 hours)"""
    aroon_down, aroon_up = talib.AROON(df['high'].values, df['low'].values, timeperiod=timeperiod)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'UP' in indicator_name:
            return aroon_up
        elif 'DOWN' in indicator_name:
            return aroon_down
    return aroon_down, aroon_up


def aroonosc(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Aroon Oscillator (intraday: 40 bars)"""
    return talib.AROONOSC(df['high'].values, df['low'].values, timeperiod=timeperiod)


def cci(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Commodity Channel Index (intraday: 40 bars)"""
    return talib.CCI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def cmo(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Chande Momentum Oscillator (intraday: 28 bars)"""
    return talib.CMO(df['close'].values, timeperiod=timeperiod)


def dx(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Directional Movement Index (intraday: 28 bars)"""
    return talib.DX(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def mfi(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Money Flow Index (intraday: 28 bars)"""
    return talib.MFI(df['high'].values, df['low'].values, df['close'].values, df['volume'].values, timeperiod=timeperiod)


def minus_di(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Minus Directional Indicator (intraday: 28 bars)"""
    return talib.MINUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def minus_dm(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Minus Directional Movement (intraday: 28 bars)"""
    return talib.MINUS_DM(df['high'].values, df['low'].values, timeperiod=timeperiod)


def mom(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Momentum (intraday: 12 bars ≈ 1 hour)"""
    return talib.MOM(df['close'].values, timeperiod=timeperiod)


def plus_di(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Plus Directional Indicator (intraday: 28 bars)"""
    return talib.PLUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


def plus_dm(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Plus Directional Movement (intraday: 28 bars)"""
    return talib.PLUS_DM(df['high'].values, df['low'].values, timeperiod=timeperiod)


def roc(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Rate of Change (intraday: 12 bars ≈ 1 hour)"""
    return talib.ROC(df['close'].values, timeperiod=timeperiod)


def rocp(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Rate of Change Percentage (intraday: 12 bars)"""
    return talib.ROCP(df['close'].values, timeperiod=timeperiod)


def rocr(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Rate of Change Ratio (intraday: 12 bars)"""
    return talib.ROCR(df['close'].values, timeperiod=timeperiod)


def rocr100(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Rate of Change Ratio 100 Scale (intraday: 12 bars)"""
    return talib.ROCR100(df['close'].values, timeperiod=timeperiod)


def rsi(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Relative Strength Index (intraday: 28 bars)"""
    return talib.RSI(df['close'].values, timeperiod=timeperiod)


def trix(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """1-day Rate-Of-Change of Triple Smooth EMA (intraday: 40 bars)"""
    return talib.TRIX(df['close'].values, timeperiod=timeperiod)


def willr(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Williams %R (intraday: 28 bars)"""
    return talib.WILLR(df['high'].values, df['low'].values, df['close'].values, timeperiod=timeperiod)


# Overlap Studies (Moving Averages)
def dema(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Double Exponential Moving Average (intraday: 40 bars)"""
    return talib.DEMA(df['close'].values, timeperiod=timeperiod)


def ema(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Exponential Moving Average (intraday: 28 bars)"""
    return talib.EMA(df['close'].values, timeperiod=timeperiod)


def kama(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Kaufman Adaptive Moving Average (intraday: 40 bars)"""
    return talib.KAMA(df['close'].values, timeperiod=timeperiod)


def ma(df: pd.DataFrame, timeperiod: int = 40, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Moving Average (intraday: 40 bars)"""
    return talib.MA(df['close'].values, timeperiod=timeperiod, matype=matype)


def midpoint(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """MidPoint over period (intraday: 28 bars)"""
    return talib.MIDPOINT(df['close'].values, timeperiod=timeperiod)


def midprice(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Midpoint Price over period (intraday: 28 bars)"""
    return talib.MIDPRICE(df['high'].values, df['low'].values, timeperiod=timeperiod)


def sma(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Simple Moving Average (intraday: 40 bars)"""
    return talib.SMA(df['close'].values, timeperiod=timeperiod)


def tema(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Triple Exponential Moving Average (intraday: 40 bars)"""
    return talib.TEMA(df['close'].values, timeperiod=timeperiod)


def trima(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Triangular Moving Average (intraday: 40 bars)"""
    return talib.TRIMA(df['close'].values, timeperiod=timeperiod)


def wma(df: pd.DataFrame, timeperiod: int = 40, indicator_name: str = None) -> np.ndarray:
    """Weighted Moving Average (intraday: 40 bars)"""
    return talib.WMA(df['close'].values, timeperiod=timeperiod)


# Math Operators (with lookback)
def max_func(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Highest value over period (intraday: 24 bars ≈ 2 hours)"""
    return talib.MAX(df['close'].values, timeperiod=timeperiod)


def maxindex(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Index of highest value over period (intraday: 24 bars)"""
    return talib.MAXINDEX(df['close'].values, timeperiod=timeperiod)


def min_func(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Lowest value over period (intraday: 24 bars)"""
    return talib.MIN(df['close'].values, timeperiod=timeperiod)


def highest_high(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Donchian channel upper — highest of HIGH prices over N periods.

    Distinct from ``max_func`` (which uses CLOSE). Use this for breakout
    strategies where the upper boundary is the rolling maximum of the
    high series, not the close series.
    """
    return talib.MAX(df['high'].values, timeperiod=timeperiod)


def lowest_low(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Donchian channel lower — lowest of LOW prices over N periods.

    Distinct from ``min_func`` (which uses CLOSE). Use this for breakout
    strategies where the lower boundary is the rolling minimum of the
    low series, not the close series.
    """
    return talib.MIN(df['low'].values, timeperiod=timeperiod)


def minindex(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Index of lowest value over period (intraday: 24 bars)"""
    return talib.MININDEX(df['close'].values, timeperiod=timeperiod)


def minmax(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Lowest and highest values over period (intraday: 24 bars)"""
    min_values, max_values = talib.MINMAX(df['close'].values, timeperiod=timeperiod)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'MIN' in indicator_name:
            return min_values
        elif 'MAX' in indicator_name:
            return max_values
    return min_values, max_values


def minmaxindex(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Indexes of lowest and highest values (intraday: 24 bars)"""
    min_indices, max_indices = talib.MINMAXINDEX(df['close'].values, timeperiod=timeperiod)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'MIN' in indicator_name:
            return min_indices
        elif 'MAX' in indicator_name:
            return max_indices
    return min_indices, max_indices


def sum_func(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Summation (intraday: 24 bars)"""
    return talib.SUM(df['close'].values, timeperiod=timeperiod)


# Statistic Functions
def beta(df: pd.DataFrame, timeperiod: int = 12, indicator_name: str = None) -> np.ndarray:
    """Beta (intraday: 12 bars)"""
    return talib.BETA(df['high'].values, df['low'].values, timeperiod=timeperiod)


def correl(df: pd.DataFrame, timeperiod: int = 24, indicator_name: str = None) -> np.ndarray:
    """Pearson's Correlation Coefficient (intraday: 24 bars)"""
    return talib.CORREL(df['high'].values, df['low'].values, timeperiod=timeperiod)


def linearreg(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Linear Regression (intraday: 28 bars)"""
    return talib.LINEARREG(df['close'].values, timeperiod=timeperiod)


def linearreg_angle(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Angle (intraday: 28 bars)"""
    return talib.LINEARREG_ANGLE(df['close'].values, timeperiod=timeperiod)


def linearreg_intercept(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Intercept (intraday: 28 bars)"""
    return talib.LINEARREG_INTERCEPT(df['close'].values, timeperiod=timeperiod)


def linearreg_slope(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Linear Regression Slope (intraday: 28 bars)"""
    return talib.LINEARREG_SLOPE(df['close'].values, timeperiod=timeperiod)


def tsf(df: pd.DataFrame, timeperiod: int = 28, indicator_name: str = None) -> np.ndarray:
    """Time Series Forecast (intraday: 28 bars)"""
    return talib.TSF(df['close'].values, timeperiod=timeperiod)


################################################################################
# SECTION 2: INDICATORS WITHOUT LOOKBACK PERIOD
################################################################################

def bop(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Balance Of Power"""
    return talib.BOP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)


def add(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Add"""
    return talib.ADD(df['high'].values, df['low'].values)


def div(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Div"""
    return talib.DIV(df['high'].values, df['low'].values)


def mult(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Mult"""
    return talib.MULT(df['high'].values, df['low'].values)


def sub(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Arithmetic Subtraction"""
    return talib.SUB(df['high'].values, df['low'].values)


def acos(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ACos"""
    return talib.ACOS(df['close'].values)


def asin(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ASin"""
    return talib.ASIN(df['close'].values)


def atan(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric ATan"""
    return talib.ATAN(df['close'].values)


def ceil(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Ceil"""
    return talib.CEIL(df['close'].values)


def cos(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Cos"""
    return talib.COS(df['close'].values)


def floor(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Floor"""
    return talib.FLOOR(df['close'].values)


def ln(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Log Natural"""
    return talib.LN(df['close'].values)


def log10(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Log10"""
    return talib.LOG10(df['close'].values)


def sin(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Sin"""
    return talib.SIN(df['close'].values)


def sqrt(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Square Root"""
    return talib.SQRT(df['close'].values)


def tan(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Tan"""
    return talib.TAN(df['close'].values)


def tanh(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Vector Trigonometric Tanh"""
    return talib.TANH(df['close'].values)


def avgprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Average Price"""
    return talib.AVGPRICE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)


def medprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Median Price"""
    return talib.MEDPRICE(df['high'].values, df['low'].values)


def typprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Typical Price"""
    return talib.TYPPRICE(df['high'].values, df['low'].values, df['close'].values)


def wclprice(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Weighted Close Price"""
    return talib.WCLPRICE(df['high'].values, df['low'].values, df['close'].values)


def trange(df: pd.DataFrame, indicator_name: str = None, **kwargs) -> np.ndarray:
    """True Range"""
    return talib.TRANGE(df['high'].values, df['low'].values, df['close'].values)


def ad(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Chaikin A/D Line"""
    return talib.AD(df['high'].values, df['low'].values, df['close'].values, df['volume'].values)


def obv(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """On Balance Volume"""
    return talib.OBV(df['close'].values, df['volume'].values)


# Cycle Indicators
def ht_dcperiod(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Dominant Cycle Period"""
    return talib.HT_DCPERIOD(df['close'].values)


def ht_dcphase(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Dominant Cycle Phase"""
    return talib.HT_DCPHASE(df['close'].values)


def ht_phasor(df: pd.DataFrame, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Hilbert Transform - Phasor Components"""
    inphase, quadrature = talib.HT_PHASOR(df['close'].values)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'INPHASE' in indicator_name:
            return inphase
        elif 'QUADRATURE' in indicator_name:
            return quadrature
    return inphase, quadrature


def ht_sine(df: pd.DataFrame, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Hilbert Transform - SineWave"""
    sine, leadsine = talib.HT_SINE(df['close'].values)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LEADSINE' in indicator_name:
            return leadsine
        elif 'SINE' in indicator_name or 'HT_SINE' in indicator_name:
            return sine
    return sine, leadsine


def ht_trendmode(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Trend vs Cycle Mode"""
    return talib.HT_TRENDMODE(df['close'].values)


def ht_trendline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    """Hilbert Transform - Instantaneous Trendline"""
    return talib.HT_TRENDLINE(df['close'].values)


################################################################################
# SECTION 3: INDICATORS WITH SPECIAL PARAMETERS (Intraday Defaults)
################################################################################

def apo(df: pd.DataFrame, fastperiod: int = 5, slowperiod: int = 13, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Absolute Price Oscillator (intraday: 5/13)"""
    return talib.APO(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, matype=matype)


def ppo(df: pd.DataFrame, fastperiod: int = 5, slowperiod: int = 13, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Percentage Price Oscillator (intraday: 5/13)"""
    return talib.PPO(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, matype=matype)


def macd(df: pd.DataFrame, fastperiod: int = 5, slowperiod: int = 13, signalperiod: int = 5, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """MACD (intraday: 5/13/5)"""
    macd_line, macd_signal, macd_histogram = talib.MACD(df['close'].values, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram
    return macd_line, macd_signal, macd_histogram


def macdext(df: pd.DataFrame, fastperiod: int = 5, fastmatype: int = 0, slowperiod: int = 13,
           slowmatype: int = 0, signalperiod: int = 5, signalmatype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """MACD with controllable MA type (intraday: 5/13/5)"""
    macd_line, macd_signal, macd_histogram = talib.MACDEXT(df['close'].values, fastperiod=fastperiod, fastmatype=fastmatype,
                                                           slowperiod=slowperiod, slowmatype=slowmatype,
                                                           signalperiod=signalperiod, signalmatype=signalmatype)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram
    return macd_line, macd_signal, macd_histogram


def macdfix(df: pd.DataFrame, signalperiod: int = 5, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """MACD Fix 12/26 (intraday signal: 5)"""
    macd_line, macd_signal, macd_histogram = talib.MACDFIX(df['close'].values, signalperiod=signalperiod)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LINE' in indicator_name:
            return macd_line
        elif 'SIGNAL' in indicator_name:
            return macd_signal
        elif 'HISTOGRAM' in indicator_name:
            return macd_histogram
    return macd_line, macd_signal, macd_histogram


def ultosc(df: pd.DataFrame, timeperiod1: int = 6, timeperiod2: int = 12, timeperiod3: int = 24, indicator_name: str = None) -> np.ndarray:
    """Ultimate Oscillator (intraday: 6/12/24)"""
    return talib.ULTOSC(df['high'].values, df['low'].values, df['close'].values, timeperiod1=timeperiod1, timeperiod2=timeperiod2, timeperiod3=timeperiod3)


def stoch(df: pd.DataFrame, fastk_period: int = 12, slowk_period: int = 3, slowk_matype: int = 0, slowd_period: int = 3, slowd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic (intraday: fastk=12)"""
    slowk, slowd = talib.STOCH(df['high'].values, df['low'].values, df['close'].values, fastk_period=fastk_period, slowk_period=slowk_period,
                               slowk_matype=slowk_matype, slowd_period=slowd_period, slowd_matype=slowd_matype)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'SLOWK' in indicator_name:
            return slowk
        elif 'SLOWD' in indicator_name:
            return slowd
    return slowk, slowd


def stochf(df: pd.DataFrame, fastk_period: int = 12, fastd_period: int = 3, fastd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic Fast (intraday: fastk=12)"""
    fastk, fastd = talib.STOCHF(df['high'].values, df['low'].values, df['close'].values, fastk_period=fastk_period, fastd_period=fastd_period, fastd_matype=fastd_matype)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FASTK' in indicator_name:
            return fastk
        elif 'FASTD' in indicator_name:
            return fastd
    return fastk, fastd


def stochrsi(df: pd.DataFrame, timeperiod: int = 28, fastk_period: int = 12, fastd_period: int = 3, fastd_matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Stochastic RSI (intraday: period=28, fastk=12)"""
    fastk, fastd = talib.STOCHRSI(df['close'].values, timeperiod=timeperiod, fastk_period=fastk_period,
                                  fastd_period=fastd_period, fastd_matype=fastd_matype)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FASTK' in indicator_name:
            return fastk
        elif 'FASTD' in indicator_name:
            return fastd
    return fastk, fastd


def bbands(df: pd.DataFrame, timeperiod: int = 20, nbdevup: float = 2, nbdevdn: float = 2, matype: int = 0, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Bollinger Bands (intraday: 20 bars)"""
    upper_band, middle_band, lower_band = talib.BBANDS(df['close'].values, timeperiod=timeperiod, nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'UPPER' in indicator_name:
            return upper_band
        elif 'MIDDLE' in indicator_name:
            return middle_band
        elif 'LOWER' in indicator_name:
            return lower_band
    return upper_band, middle_band, lower_band


def mama(df: pd.DataFrame, fastlimit: float = 0.5, slowlimit: float = 0.05, indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """MESA Adaptive Moving Average"""
    mama_values, fama_values = talib.MAMA(df['close'].values, fastlimit=fastlimit, slowlimit=slowlimit)
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'FAMA' in indicator_name:
            return fama_values
        elif 'MAMA' in indicator_name:
            return mama_values
    return mama_values, fama_values


def mavp(df: pd.DataFrame, periods: np.ndarray = None, minperiod: int = 2, maxperiod: int = 24, matype: int = 0, indicator_name: str = None) -> np.ndarray:
    """Moving average with variable period (intraday: maxperiod=24)"""
    if periods is None:
        periods = np.full(len(df), 24, dtype=np.float64)
    return talib.MAVP(df['close'].values, periods, minperiod=minperiod, maxperiod=maxperiod, matype=matype)


def sar(df: pd.DataFrame, acceleration: float = 0.02, maximum: float = 0.2, indicator_name: str = None) -> np.ndarray:
    """Parabolic SAR"""
    return talib.SAR(df['high'].values, df['low'].values, acceleration=acceleration, maximum=maximum)


def sarext(df: pd.DataFrame, startvalue: float = 0, offsetonreverse: float = 0,
          accelerationinitlong: float = 0.02, accelerationlong: float = 0.02, accelerationmaxlong: float = 0.2,
          accelerationinitshort: float = 0.02, accelerationshort: float = 0.02, accelerationmaxshort: float = 0.2, indicator_name: str = None) -> np.ndarray:
    """Parabolic SAR - Extended"""
    return talib.SAREXT(df['high'].values, df['low'].values, startvalue=startvalue, offsetonreverse=offsetonreverse,
                        accelerationinitlong=accelerationinitlong, accelerationlong=accelerationlong,
                        accelerationmaxlong=accelerationmaxlong, accelerationinitshort=accelerationinitshort,
                        accelerationshort=accelerationshort, accelerationmaxshort=accelerationmaxshort)


def t3(df: pd.DataFrame, timeperiod: int = 12, vfactor: float = 0, indicator_name: str = None) -> np.ndarray:
    """Triple Exponential Moving Average T3 (intraday: 12 bars)"""
    return talib.T3(df['close'].values, timeperiod=timeperiod, vfactor=vfactor)


def stddev(df: pd.DataFrame, timeperiod: int = 12, nbdev: float = 1, indicator_name: str = None) -> np.ndarray:
    """Standard Deviation (intraday: 12 bars)"""
    return talib.STDDEV(df['close'].values, timeperiod=timeperiod, nbdev=nbdev)


def var(df: pd.DataFrame, timeperiod: int = 12, nbdev: float = 1, indicator_name: str = None) -> np.ndarray:
    """Variance (intraday: 12 bars)"""
    return talib.VAR(df['close'].values, timeperiod=timeperiod, nbdev=nbdev)


def adosc(df: pd.DataFrame, fastperiod: int = 3, slowperiod: int = 10, indicator_name: str = None) -> np.ndarray:
    """Chaikin A/D Oscillator"""
    return talib.ADOSC(df['high'].values, df['low'].values, df['close'].values, df['volume'].values, fastperiod=fastperiod, slowperiod=slowperiod)


################################################################################
# SECTION 4: CANDLESTICK PATTERNS (No changes for intraday)
################################################################################

def cdl2crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL2CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3blackcrows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3BLACKCROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3inside(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3INSIDE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3linestrike(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3LINESTRIKE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3outside(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3OUTSIDE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3starsinsouth(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3STARSINSOUTH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdl3whitesoldiers(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDL3WHITESOLDIERS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlabandonedbaby(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    return talib.CDLABANDONEDBABY(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdladvanceblock(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLADVANCEBLOCK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlbelthold(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLBELTHOLD(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlbreakaway(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLBREAKAWAY(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlclosingmarubozu(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLCLOSINGMARUBOZU(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlconcealbabyswall(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLCONCEALBABYSWALL(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlcounterattack(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLCOUNTERATTACK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdldarkcloudcover(df: pd.DataFrame, penetration: float = 0.5, indicator_name: str = None) -> np.ndarray:
    return talib.CDLDARKCLOUDCOVER(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdldoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdldojistar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdldragonflydoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLDRAGONFLYDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlengulfing(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLENGULFING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdleveningdojistar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    return talib.CDLEVENINGDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdleveningstar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    return talib.CDLEVENINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdlgapsidesidewhite(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLGAPSIDESIDEWHITE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlgravestonedoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLGRAVESTONEDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhammer(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHAMMER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhangingman(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHANGINGMAN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlharami(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHARAMI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlharamicross(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHARAMICROSS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhighwave(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHIGHWAVE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhikkake(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHIKKAKE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhikkakemod(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHIKKAKEMOD(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlhomingpigeon(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLHOMINGPIGEON(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlidentical3crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLIDENTICAL3CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlinneck(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLINNECK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlinvertedhammer(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLINVERTEDHAMMER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlkicking(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLKICKING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlkickingbylength(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLKICKINGBYLENGTH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlladderbottom(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLLADDERBOTTOM(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdllongleggeddoji(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLLONGLEGGEDDOJI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdllongline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLLONGLINE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlmarubozu(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLMARUBOZU(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlmatchinglow(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLMATCHINGLOW(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlmathold(df: pd.DataFrame, penetration: float = 0.5, indicator_name: str = None) -> np.ndarray:
    return talib.CDLMATHOLD(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdlmorningdojistar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    return talib.CDLMORNINGDOJISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdlmorningstar(df: pd.DataFrame, penetration: float = 0.3, indicator_name: str = None) -> np.ndarray:
    return talib.CDLMORNINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values, penetration=penetration)

def cdlonneck(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLONNECK(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlpiercing(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLPIERCING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlrickshawman(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLRICKSHAWMAN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlrisefall3methods(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLRISEFALL3METHODS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlseparatinglines(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSEPARATINGLINES(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlshootingstar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSHOOTINGSTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlshortline(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSHORTLINE(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlspinningtop(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSPINNINGTOP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlstalledpattern(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSTALLEDPATTERN(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlsticksandwich(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLSTICKSANDWICH(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdltakuri(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLTAKURI(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdltasukigap(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLTASUKIGAP(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlthrusting(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLTHRUSTING(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdltristar(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLTRISTAR(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlunique3river(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLUNIQUE3RIVER(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlupsidegap2crows(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLUPSIDEGAP2CROWS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)

def cdlxsidegap3methods(df: pd.DataFrame, indicator_name: str = None) -> np.ndarray:
    return talib.CDLXSIDEGAP3METHODS(df['open'].values, df['high'].values, df['low'].values, df['close'].values)


################################################################################
# SECTION 5: BATCH CALCULATION FUNCTION (Legacy)
################################################################################


def calculate_technical_indicators(
    df: pd.DataFrame,
    config: Dict[str, Any]
) -> pd.DataFrame:
    """
    Calculate all technical indicators for intraday data.

    Args:
        df: DataFrame with OHLCV columns
        config: Configuration with indicator periods

    Returns:
        DataFrame with indicator columns added
    """
    result = df.copy()

    high = result['high'].values
    low = result['low'].values
    close = result['close'].values
    volume = result['volume'].values if 'volume' in result.columns else None

    # =====================================================================
    # Tier 1: Momentum Indicators (optimizable periods)
    # =====================================================================

    # RSI
    rsi_period = config.get('rsi_period', 28)
    result[f'rsi_{rsi_period}'] = talib.RSI(close, timeperiod=rsi_period)

    # CCI
    cci_period = config.get('cci_period', 40)
    result[f'cci_{cci_period}'] = talib.CCI(high, low, close, timeperiod=cci_period)

    # Williams %R
    willr_period = config.get('willr_period', 28)
    result[f'willr_{willr_period}'] = talib.WILLR(high, low, close, timeperiod=willr_period)

    # MFI (if volume available)
    if volume is not None:
        mfi_period = config.get('mfi_period', 28)
        result[f'mfi_{mfi_period}'] = talib.MFI(high, low, close, volume, timeperiod=mfi_period)

    # =====================================================================
    # Tier 1: Trend Indicators
    # =====================================================================

    # ADX and DI
    adx_period = config.get('adx_period', 28)
    result[f'adx_{adx_period}'] = talib.ADX(high, low, close, timeperiod=adx_period)
    result[f'plus_di_{adx_period}'] = talib.PLUS_DI(high, low, close, timeperiod=adx_period)
    result[f'minus_di_{adx_period}'] = talib.MINUS_DI(high, low, close, timeperiod=adx_period)

    # Aroon Oscillator
    aroonosc_period = config.get('aroonosc_period', 40)
    result[f'aroonosc_{aroonosc_period}'] = talib.AROONOSC(high, low, timeperiod=aroonosc_period)

    # =====================================================================
    # Tier 1: Volatility Indicators
    # =====================================================================

    # ATR
    atr_period = config.get('atr_period', 28)
    result[f'atr_{atr_period}'] = talib.ATR(high, low, close, timeperiod=atr_period)

    # NATR (Normalized ATR)
    result[f'natr_{atr_period}'] = talib.NATR(high, low, close, timeperiod=atr_period)

    # =====================================================================
    # Tier 1: Moving Averages
    # =====================================================================

    # EMAs
    ema_fast = config.get('ema_fast', 20)
    ema_slow = config.get('ema_slow', 40)
    result[f'ema_{ema_fast}'] = talib.EMA(close, timeperiod=ema_fast)
    result[f'ema_{ema_slow}'] = talib.EMA(close, timeperiod=ema_slow)

    # SMAs
    sma_short = config.get('sma_short', 30)
    sma_mid = config.get('sma_mid', 60)
    result[f'sma_{sma_short}'] = talib.SMA(close, timeperiod=sma_short)
    result[f'sma_{sma_mid}'] = talib.SMA(close, timeperiod=sma_mid)

    # =====================================================================
    # Tier 2: Fixed Parameter Indicators
    # =====================================================================

    # MACD (intraday calibrated: 5, 13, 5)
    macd_fast = config.get('macd_fast', 5)
    macd_slow = config.get('macd_slow', 13)
    macd_signal = config.get('macd_signal', 5)

    macd, macd_sig, macd_hist = talib.MACD(
        close,
        fastperiod=macd_fast,
        slowperiod=macd_slow,
        signalperiod=macd_signal
    )
    result['macd'] = macd
    result['macd_signal'] = macd_sig
    result['macd_hist'] = macd_hist

    # Bollinger Bands
    bb_period = config.get('bb_period', 20)
    bb_std = config.get('bb_std', 2.0)

    bb_upper, bb_middle, bb_lower = talib.BBANDS(
        close,
        timeperiod=bb_period,
        nbdevup=bb_std,
        nbdevdn=bb_std
    )
    result['bb_upper'] = bb_upper
    result['bb_middle'] = bb_middle
    result['bb_lower'] = bb_lower

    # BB position (where is price within bands, 0-100)
    bb_range = bb_upper - bb_lower
    result['bb_position'] = np.where(
        bb_range > 0,
        (close - bb_lower) / bb_range * 100,
        50
    )

    # BB width (volatility proxy)
    result['bb_width'] = bb_range / bb_middle * 100

    # =====================================================================
    # Tier 2: Price Channel
    # =====================================================================

    # Highest High / Lowest Low (for support/resistance)
    for period in [12, 24, 48]:  # ~1h, 2h, 4h on 5-min bars
        result[f'highest_high_{period}'] = talib.MAX(high, timeperiod=period)
        result[f'lowest_low_{period}'] = talib.MIN(low, timeperiod=period)

    # =====================================================================
    # Tier 2: Momentum Derivatives
    # =====================================================================

    # ROC (Rate of Change)
    for period in [6, 12, 24]:  # ~30min, 1h, 2h
        result[f'roc_{period}'] = talib.ROC(close, timeperiod=period)

    # =====================================================================
    # Tier 2: Volume Indicators (if volume available)
    # =====================================================================

    if volume is not None:
        # OBV
        result['obv'] = talib.OBV(close, volume)

        # AD (Accumulation/Distribution)
        result['ad'] = talib.AD(high, low, close, volume)

        # ADOSC (Chaikin A/D Oscillator)
        result['adosc'] = talib.ADOSC(high, low, close, volume,
                                       fastperiod=3, slowperiod=10)

    # =====================================================================
    # Derived Signals
    # =====================================================================

    # Trend direction (fast EMA vs slow EMA)
    result['trend_direction'] = np.where(
        result[f'ema_{ema_fast}'] > result[f'ema_{ema_slow}'], 1,
        np.where(result[f'ema_{ema_fast}'] < result[f'ema_{ema_slow}'], -1, 0)
    )

    # RSI zones
    result['rsi_zone'] = pd.cut(
        result[f'rsi_{rsi_period}'],
        bins=[0, 30, 70, 100],
        labels=['oversold', 'neutral', 'overbought']
    )

    return result


# =============================================================================
# Indicator Tier Classification
# =============================================================================

TIER1_INDICATORS = [
    # Momentum
    'rsi', 'cci', 'willr', 'mfi',
    # Trend
    'adx', 'plus_di', 'minus_di', 'aroonosc',
    # Volatility
    'atr', 'natr',
    # Moving Averages
    'ema', 'sma', 'dema', 'tema', 'wma', 'kama',
    # Price levels
    'highest_high', 'lowest_low',
]

TIER2_INDICATORS = [
    # MACD (fixed params)
    'macd', 'macd_signal', 'macd_hist',
    # Bollinger Bands
    'bb_upper', 'bb_middle', 'bb_lower', 'bb_position', 'bb_width',
    # Volume
    'obv', 'ad', 'adosc',
    # Momentum derivatives
    'roc',
    # Session indicators
    'vwap', 'vwap_distance_pct',
    'session_high', 'session_low', 'session_position_pct',
    'night_or_high', 'night_or_low', 'day_or_high', 'day_or_low',
]

TIER3_INDICATORS = [
    # Regime classification
    'session_phase',
    'market_state', 'market_state_str',
    'is_tradeable',
    # Time features
    'hour_of_day', 'bar_of_day',
]


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    # Test with sample data
    import pandas as pd
    import numpy as np

    n = 200
    np.random.seed(42)

    close = 20000 + np.cumsum(np.random.randn(n) * 10)
    high = close + np.abs(np.random.randn(n) * 5)
    low = close - np.abs(np.random.randn(n) * 5)
    volume = np.abs(np.random.randn(n) * 1000) + 500

    df = pd.DataFrame({
        'open': close + np.random.randn(n) * 3,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })

    config = {
        'rsi_period': 28,
        'cci_period': 40,
        'adx_period': 28,
        'atr_period': 28,
        'ema_fast': 20,
        'ema_slow': 40,
        'sma_short': 30,
        'sma_mid': 60,
    }

    df = calculate_technical_indicators(df, config)

    print("Calculated indicators:")
    print(df.columns.tolist())
    print(f"\nTotal columns: {len(df.columns)}")
