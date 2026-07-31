"""Bounds tests for shfe_bands — guard against typo'd or accidentally-relaxed bands."""
from echolon.live.config.shfe_bands import (
    SHFE_DAILY_BAND_PCT, DEFAULT_BAND_PCT, band_pct_for, product_code,
)


def test_all_bands_in_legal_range():
    """Every configured band must be in (0, 0.20]. SHFE bands are typically
    5-10%; values above 20% would suggest a typo."""
    for symbol, pct in SHFE_DAILY_BAND_PCT.items():
        assert 0 < pct <= 0.20, f"{symbol} band {pct} outside legal range"


def test_default_band_pct_in_legal_range():
    assert 0 < DEFAULT_BAND_PCT <= 0.20


def test_default_band_pct_at_least_max_configured():
    """Fallback should be at least as permissive as the most permissive
    configured value (otherwise unknown instruments get unsafely tight bands)."""
    assert DEFAULT_BAND_PCT >= max(SHFE_DAILY_BAND_PCT.values())


def test_band_pct_for_unknown_symbol_returns_default():
    assert band_pct_for("xx2606.SF") == DEFAULT_BAND_PCT


def test_band_pct_for_known_symbol_returns_configured():
    assert band_pct_for("al2606.SF") == SHFE_DAILY_BAND_PCT["al"]
    assert band_pct_for("cu2606.SF") == SHFE_DAILY_BAND_PCT["cu"]


def test_product_code_extracts_from_symbol():
    assert product_code("al2606.SF") == "al"
    assert product_code("cu2606.SF") == "cu"
