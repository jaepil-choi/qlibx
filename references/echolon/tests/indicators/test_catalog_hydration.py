"""Catalog hydration tests — Phase F-5 updated for has_lookback contract.

Originally written TDD-style for Phase A1 (cluster-based hydration). Phase F-5
collapsed the 4-way cluster split to a single ``has_lookback`` boolean derived
from function signatures (period-like params → True). Tests updated accordingly.
"""
from echolon.indicators import catalog


def test_catalog_has_at_least_170_entries():
    names = catalog.list_all()
    assert len(names) >= 170, f"Expected >= 170 entries, got {len(names)}"


def test_catalog_supports_has_lookback_filter_true():
    lookback = set(catalog.list_all(has_lookback=True))
    for expected in ("rsi", "atr", "adx", "ema"):
        assert expected in lookback, (
            f"'{expected}' missing from has_lookback=True; "
            f"got sample: {sorted(lookback)[:10]}"
        )


def test_catalog_has_lookback_filter_false_excludes_lookback_names():
    no_lookback = set(catalog.list_all(has_lookback=False))
    for name in ("rsi", "atr", "adx", "ema"):
        assert name not in no_lookback, (
            f"'{name}' should NOT appear in has_lookback=False"
        )


def test_catalog_info_returns_has_lookback_and_params_for_rsi():
    rsi = catalog.info("rsi")
    assert rsi is not None
    assert rsi.has_lookback is True
    param_names = [p["name"] for p in rsi.params]
    assert "timeperiod" in param_names, f"timeperiod not in params: {param_names}"
    tp = next(p for p in rsi.params if p["name"] == "timeperiod")
    assert tp["default"] == 14, f"Expected default=14, got {tp['default']}"


def test_catalog_info_bbands_upper_has_lookback_true():
    """BBANDS has timeperiod → has_lookback=True. Phase F-5 collapsed the
    previous 'indicators_with_special_params' category into has_lookback=True
    because BBANDS does have a sweepable period."""
    bbands_upper = catalog.info("bbands_upper")
    assert bbands_upper is not None
    assert bbands_upper.has_lookback is True


def test_catalog_info_obv_has_lookback_false():
    obv = catalog.info("obv")
    assert obv is not None
    assert obv.has_lookback is False


def test_catalog_info_is_case_insensitive():
    upper = catalog.info("RSI")
    lower = catalog.info("rsi")
    assert upper is not None
    assert lower is not None
    assert upper.name == lower.name
    assert upper.has_lookback == lower.has_lookback
    assert upper.params == lower.params


def test_catalog_info_unknown_returns_none():
    assert catalog.info("fake_indicator_xyz_123") is None
    assert catalog.info("SPEAK_BLUE_TURTLE_INDEX") is None
    assert catalog.info("") is None


def test_catalog_list_all_is_sorted():
    names = catalog.list_all()
    assert names == sorted(names), "list_all() must return sorted names"


def test_catalog_list_all_filter_subsets_all_names():
    all_names = set(catalog.list_all())
    lookback = set(catalog.list_all(has_lookback=True))
    no_lookback = set(catalog.list_all(has_lookback=False))
    assert lookback.issubset(all_names)
    assert no_lookback.issubset(all_names)
    # Partition: every name is in exactly one of the two filters.
    assert lookback.isdisjoint(no_lookback)
    assert lookback | no_lookback == all_names


def test_catalog_info_has_function_and_file():
    rsi = catalog.info("rsi")
    assert rsi is not None
    assert rsi.function == "rsi"
    assert rsi.file == "ta_lib"


def test_catalog_bbands_entries_share_params():
    """BBANDS_UPPER/MIDDLE/LOWER all dispatch to bbands(); params must match."""
    upper = catalog.info("bbands_upper")
    middle = catalog.info("bbands_middle")
    lower = catalog.info("bbands_lower")
    assert upper is not None and middle is not None and lower is not None
    # All three share the same underlying function and therefore the same params
    assert upper.params == middle.params == lower.params
    param_names = {p["name"] for p in upper.params}
    assert {"timeperiod", "nbdevup", "nbdevdn", "matype"}.issubset(param_names), (
        f"bbands params should include timeperiod/nbdevup/nbdevdn/matype, got {param_names}"
    )
