"""Carry indicators in the catalog — Step 1 of the carry catalog refactor.

The 5 forward-curve carry indicators are intentionally NOT in INDICATOR_MAPPING
(they take a multi-contract curve_snapshot, not a single-contract df). Before
this change they were invisible to ``catalog.info`` / ``validate`` — so the
qorka coding/QC agents (which delegate to this catalog) concluded carry "isn't a
real indicator" and deleted it. They must now be discoverable, tagged by kind +
compute_source, while staying out of the per-contract ta-lib map.
"""
from echolon.indicators import catalog

CARRY_NAMES = (
    "carry_front_back",
    "curve_slope_near",
    "risk_adj_carry",
    "carry_z_3m",
    "carry_change_20d",
)


def test_carry_indicators_present_in_catalog():
    names = set(catalog.list_all())
    for n in CARRY_NAMES:
        assert n in names, f"{n} missing from catalog.list_all()"


def test_carry_info_tagged_curve_kind_and_curve_stage_source():
    cfb = catalog.info("carry_front_back")
    assert cfb is not None
    assert cfb.kind == "curve_carry"
    # Step 2: carry is computed engine-side by the curve stage (Path-B retired).
    assert cfb.compute_source == "echolon_curve_stage"
    assert cfb.requires == "forward_curve_snapshot"
    assert cfb.output == "per_date_scalar_broadcast"


def test_carry_indicator_params_match_calc_defaults():
    z = catalog.info("carry_z_3m")
    assert z is not None
    window = next((p for p in z.params if p["name"] == "window"), None)
    assert window is not None, f"window param missing: {z.params}"
    assert window["default"] == 63

    change = catalog.info("carry_change_20d")
    lag = next((p for p in change.params if p["name"] == "lag"), None)
    assert lag is not None and lag["default"] == 20

    # data-input args (curve_snapshot / series) are NOT exposed as tunable params
    cfb = catalog.info("carry_front_back")
    assert all(p["name"] not in ("curve_snapshot", "carry_history",
                                 "front_settlement_series") for p in cfb.params)


def test_talib_indicators_retain_per_contract_kind():
    # Regression: existing ta-lib entries keep the per-contract pipeline kind.
    atr = catalog.info("atr")
    assert atr is not None
    assert atr.kind == "per_contract_talib"
    assert atr.compute_source == "echolon_pipeline"
    assert atr.requires == "single_contract_ohlcv"


def test_validate_accepts_carry_name_ind004_retired():
    # The old IND-004 "unknown indicator" rejection of carry is retired:
    # a declared carry name now validates clean against the catalog.
    errors = catalog.validate({"carry_front_back": {}})
    assert errors == [], f"carry_front_back should validate clean, got: {errors}"


def test_validate_rejects_any_param_on_curve_carry():
    # curve_carry indicators are param-FREE in a declaration: the curve stage uses
    # fixed pool-default windows and the processor raises on any non-empty spec.
    # validate must reject a param at the codegen gate (loud-at-validation, not
    # deferred to backtest) — including an ADVERTISED param like window (catalog.info
    # shows window=63 for discoverability, but it is not declarable).
    assert catalog.validate({"carry_z_3m": {}}) == []
    swept = catalog.validate({"carry_z_3m": {"window": [40, 80]}})
    assert any(e["code"] == "IND-005" for e in swept), swept
    scalar = catalog.validate({"carry_z_3m": {"window": 40}})
    assert any(e["code"] == "IND-005" for e in scalar), scalar
    # carry_front_back (params=[]) likewise rejects any param
    assert any(e["code"] == "IND-005" for e in catalog.validate({"carry_front_back": {"x": 1}}))
