"""Phase A1 — Tests for catalog.validate() and catalog.suggest_similar().

These tests are written FIRST (TDD). They fail against the current catalog.py
which has no validate() or suggest_similar() functions.
"""
from echolon.indicators import catalog


def test_validate_empty_dict_is_valid():
    """Empty flat-dict passes — schema's _reject_empty handles non-emptiness elsewhere."""
    errors = catalog.validate({})
    assert errors == []


def test_validate_unknown_name_returns_error_with_suggestions():
    errors = catalog.validate({"fake_rsi": {}})
    assert len(errors) == 1
    err = errors[0]
    assert err["field"] == "fake_rsi"
    assert "code" in err
    assert "message" in err
    assert "suggestion" in err
    # difflib should find "rsi" as a close match
    assert "rsi" in err["suggestion"], (
        f"Expected 'rsi' in suggestions, got: {err['suggestion']}"
    )


def test_validate_known_indicator_with_valid_params_passes():
    """rsi with a valid timeperiod range should produce no errors."""
    errors = catalog.validate({"rsi": {"timeperiod": [10, 20]}})
    assert errors == [], f"Expected no errors, got: {errors}"


def test_validate_known_indicator_no_params_passes():
    """A known indicator with an empty params dict is valid."""
    errors = catalog.validate({"obv": {}})
    assert errors == [], f"Expected no errors for obv, got: {errors}"


def test_validate_known_indicator_with_unknown_param_fails():
    """An unrecognized param key for a known indicator is an error."""
    errors = catalog.validate({"rsi": {"fakeperiod": 5}})
    assert len(errors) >= 1
    fields = [e["field"] for e in errors]
    assert any("rsi" in f or "fakeperiod" in f for f in fields), (
        f"Expected field referencing 'rsi' or 'fakeperiod', got: {fields}"
    )


def test_validate_lookback_rejects_min_gt_max():
    """For lookback indicators, timeperiod=[20, 10] is invalid."""
    errors = catalog.validate({"rsi": {"timeperiod": [20, 10]}})
    assert len(errors) >= 1
    fields = [e["field"] for e in errors]
    messages = [e["message"] for e in errors]
    assert (
        any("rsi" in f for f in fields)
        or any("timeperiod" in m for m in messages)
    ), f"Expected error about rsi/timeperiod min>max, got fields={fields}, msgs={messages}"


def test_validate_multiple_unknown_names_returns_one_error_per_name():
    errors = catalog.validate({"fake_one": {}, "fake_two": {}})
    assert len(errors) == 2
    fields = {e["field"] for e in errors}
    assert fields == {"fake_one", "fake_two"}


def test_suggest_similar_exact_match_returned():
    results = catalog.suggest_similar("rsi")
    assert "rsi" in results, f"Expected 'rsi' in suggest_similar('rsi'), got: {results}"


def test_suggest_similar_returns_at_most_limit():
    results = catalog.suggest_similar("rsi", limit=3)
    assert len(results) <= 3


def test_suggest_similar_unknown_gibberish_returns_empty_or_short():
    results = catalog.suggest_similar("zzzzqqqxxx_gibberish_abc")
    assert isinstance(results, list)
    assert len(results) <= 5


def test_suggest_similar_empty_name_returns_empty_list():
    assert catalog.suggest_similar("") == []


# ---------------------------------------------------------------------------
# Phase G follow-up: registered classifier names are valid in indicator_list
# (the processor dispatches them via is_registered_classifier; the validator
# must agree so they can reach the processor).
# ---------------------------------------------------------------------------


def test_validate_accepts_registered_classifier_name():
    """Names registered in the regime classifier registry must pass
    catalog.validate(), even though they aren't in the static catalog."""
    import numpy as np
    import pandas as pd
    from echolon.indicators.registry import register_regime_classifier
    from echolon.indicators.registry.regime_classifiers import _CLASSIFIERS

    class _StubClassifier:
        name = "test_catalog_validate_stub"
        label_map = {0: "x"}

        def fit_classify(self, df, params):
            return pd.Series(np.zeros(len(df), dtype=int), index=df.index)

    register_regime_classifier(_StubClassifier())
    try:
        errors = catalog.validate({"test_catalog_validate_stub": {}})
        assert errors == [], f"Expected registered classifier to validate, got: {errors}"

        mixed = catalog.validate({"rsi": {}, "test_catalog_validate_stub": {"foo": 1}})
        assert mixed == [], f"Mixed catalog+classifier dict should validate, got: {mixed}"
    finally:
        _CLASSIFIERS.pop("test_catalog_validate_stub", None)


def test_validate_unknown_name_still_fails_when_no_classifier_registered():
    """Unknown names that are NOT registered classifiers still raise IND-004."""
    errors = catalog.validate({"definitely_not_a_real_classifier_xyz": {}})
    assert len(errors) == 1
    assert errors[0]["code"] == "IND-004"
