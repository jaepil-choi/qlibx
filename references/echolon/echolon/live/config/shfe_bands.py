"""SHFE per-instrument daily-band configuration.

The exchange publishes a max daily price move (涨跌停板) as a percentage
of the previous settlement price. Bands vary by instrument and SHFE may
adjust them mid-session in volatile conditions; the table here reflects
typical bands as of 2026-05.

Used by:
- ``BandGuard`` (Layer 5) to refuse orders priced outside the band.
- ``kill_at_band_edge_price`` (Amendment B) to compute the maximally
  aggressive limit for ABANDONED-EXIT recovery.

If SHFE adjusts an instrument's band intra-day, override here.
"""

from typing import Dict


# Band as a fraction of previous settlement (e.g. 0.07 = ±7%).
SHFE_DAILY_BAND_PCT: Dict[str, float] = {
    # Non-ferrous metals
    "al": 0.07, "cu": 0.07, "zn": 0.07, "pb": 0.07, "ni": 0.07, "sn": 0.07,
    # Precious metals
    "au": 0.05, "ag": 0.05,
    # Ferrous metals
    "rb": 0.05, "hc": 0.05, "ss": 0.05,
    # Energy / chemical
    "bu": 0.06, "ru": 0.06, "fu": 0.06, "sp": 0.06, "nr": 0.06,
}

# Defensive default for any instrument we haven't tabulated.
DEFAULT_BAND_PCT: float = 0.07


def product_code(symbol: str) -> str:
    """Extract product code from a contract symbol.

    Examples:
        'al2606.SF' -> 'al'
        'cu2607.SF' -> 'cu'
    """
    base = symbol.split(".")[0]
    return "".join(c for c in base if c.isalpha()).lower()


def band_pct_for(symbol: str) -> float:
    """Look up the daily band fraction for a contract."""
    return SHFE_DAILY_BAND_PCT.get(product_code(symbol), DEFAULT_BAND_PCT)
