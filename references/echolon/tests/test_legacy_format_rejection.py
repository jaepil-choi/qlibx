"""A2 — legacy section-keyed indicator-list format gives ONE clean migration
error (IND-008), not 3-4× junk IND-004 "unknown indicator
'indicators_with_lookback'".

The deprecated three/four-section shape (still embedded in the deployed al_s1
reference, e.g. strategy_code_combined.py) seeded a coding agent's flat-dict vs
three-section oscillation: feeding it to catalog.validate treated each SECTION
KEY as an indicator name and emitted a junk IND-004 per section. One clear
"migrate to flat-dict" error is actionable; N junk errors are noise.

Authoritative sentinel set mirrors qorka's
``coding_agent/hooks/json_schema_hook._LEGACY_SECTION_KEYS``.
"""
from echolon.indicators import catalog


def test_legacy_two_section_payload_returns_single_ind008():
    payload = {
        "indicators_with_lookback": {"rsi": {"timeperiod": [10, 20]}},
        "indicators_without_lookback": {"obv": {}},
    }
    errors = catalog.validate(payload)
    assert len(errors) == 1, errors
    assert errors[0]["code"] == "IND-008"
    assert "flat-dict" in errors[0]["message"].lower()


def test_legacy_special_params_section_detected():
    errors = catalog.validate({"indicators_with_special_params": {"market_regime": {}}})
    assert len(errors) == 1
    assert errors[0]["code"] == "IND-008"


def test_legacy_system_provided_section_detected():
    errors = catalog.validate({"system_provided_indicators": {"market_regime": {}}})
    assert errors and errors[0]["code"] == "IND-008"


def test_legacy_takes_priority_over_per_name_ind004():
    """Even when a section also nests an unknown name, the agent gets the ONE
    structural migration hint, not that plus junk per-name IND-004s."""
    errors = catalog.validate({"indicators_with_lookback": {"totally_fake_xyz": {}}})
    assert [e["code"] for e in errors] == ["IND-008"]


def test_flat_dict_with_normal_indicators_not_flagged_as_legacy():
    errors = catalog.validate({"rsi": {"timeperiod": [10, 20]}, "market_regime": {}, "obv": {}})
    assert not any(e["code"] == "IND-008" for e in errors)


def test_empty_dict_not_flagged_as_legacy():
    assert catalog.validate({}) == []
