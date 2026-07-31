"""Contract-spec falsifiers for the panel-v5 additions (FV3 WP-X1b).

Only ``multiplier`` and ``tick_size`` are asserted: they are exchange contract
specifications, verified 2026-07-19 against akshare ``futures_contract_info_gfex``
/ ``futures_contract_info_czce`` / ``futures_fees_info`` (合约乘数/最小跳动).
``margin_rate``/``commission`` are deliberately NOT asserted here because they are
broker-observed, time-varying snapshots, not authoritative specs.
"""

from __future__ import annotations

from echolon.config.markets.czce.instruments import INSTRUMENTS as CZCE
from echolon.config.markets.dce.instruments import INSTRUMENTS as DCE
from echolon.config.markets.gfex.instruments import INSTRUMENTS as GFEX
from echolon.config.markets.shfe.instruments import (
    INSTRUMENTS as SHFE,
    get_by_category,
)

# (registry, code): (market, multiplier, tick_size) — authoritative, verified.
VERIFIED_SPECS = {
    ("GFEX", "si"): ("GFEX", 5.0, 5.0),
    ("SHFE", "ao"): ("SHFE", 20.0, 1.0),
    ("CZCE", "ap"): ("CZCE", 10.0, 1.0),
    ("CZCE", "cj"): ("CZCE", 5.0, 5.0),
    ("CZCE", "pk"): ("CZCE", 5.0, 2.0),
    ("DCE", "eb"): ("DCE", 5.0, 1.0),
    ("DCE", "a"): ("DCE", 10.0, 1.0),
    ("DCE", "b"): ("DCE", 10.0, 1.0),
    ("DCE", "cs"): ("DCE", 10.0, 1.0),
}

_REGISTRIES = {"GFEX": GFEX, "SHFE": SHFE, "CZCE": CZCE, "DCE": DCE}


def test_new_specs_present_with_verified_multiplier_and_tick() -> None:
    for (registry_name, code), (market, mult, tick) in VERIFIED_SPECS.items():
        spec = _REGISTRIES[registry_name][code]
        assert spec.code == code
        assert spec.market == market
        assert spec.multiplier == mult, (code, spec.multiplier)
        assert spec.tick_size == tick, (code, spec.tick_size)
        assert spec.commission_type in {"per_contract", "percentage"}
        assert spec.margin_rate > 0


def test_ao_registered_in_base_metals_category() -> None:
    assert "ao" in get_by_category("base_metals")


def test_existing_pb_ss_specs_unchanged() -> None:
    # Regression anchor: the incumbent SHFE pb/ss specs (already correct against
    # akshare) must not drift while ao is added alongside them.
    assert (SHFE["pb"].multiplier, SHFE["pb"].tick_size) == (5.0, 5.0)
    assert (SHFE["ss"].multiplier, SHFE["ss"].tick_size) == (5.0, 5.0)


def test_echolon_reconciles_with_qorka_universe_screen_multiplier_tick() -> None:
    """Echolon-side reconciliation anchor for the overlapping products duplicated
    in qorka's ``universe_screen.py`` (pb/ss + the AP/PK/CJ bench candidates).

    Echolon cannot import qorka, so qorka's (multiplier, tick) values are pinned
    here from that file. Any drift on the echolon side trips this test; the
    cross-repo consistency test that imports both is a deferred qorka task.
    """
    qorka_multiplier_tick = {
        ("SHFE", "pb"): (5.0, 5.0),
        ("SHFE", "ss"): (5.0, 5.0),
        ("CZCE", "ap"): (10.0, 1.0),
        ("CZCE", "pk"): (5.0, 2.0),
        ("CZCE", "cj"): (5.0, 5.0),
    }
    for (market, code), (mult, tick) in qorka_multiplier_tick.items():
        spec = _REGISTRIES[market][code]
        assert (spec.multiplier, spec.tick_size) == (mult, tick), code
