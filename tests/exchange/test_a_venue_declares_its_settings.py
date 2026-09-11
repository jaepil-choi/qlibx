"""Design §6.1: what a venue models is its own setting, declared as data and recorded.

`KrxExchange` takes its rates as constructor arguments -- from code as `Decimal`, from a registered
config as decimal strings -- and `settings` is the docstring's *implemented / not implemented*
claim written down: the record carries it, the loader refuses a venue whose declaration cannot be
written down, and a tax-free KRX charges no tax while saying so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.exchange.support import execution_call
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.instrument import InstrumentRoster, instrument
from vqapr.domain.memory import normalize_memory
from vqapr.domain.order import OrderBatch, OrderRequest
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import (
    COMMISSION_RATE,
    KRX_NOT_MODELLED,
    SALE_TAX_RATE,
    KrxExchange,
    KrxSettings,
    krx_listings,
)
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_exchange

NAME = "A005930"
AT = datetime(2024, 3, 5, 6, 30, tzinfo=UTC)
ROSTER = InstrumentRoster({NAME: instrument(NAME, "stock")})


def _sell(quantity: Decimal, price: Decimal) -> OrderBatch:
    return OrderBatch(
        0, (OrderRequest(NAME, quantity, Decimal("0"), -quantity, price, None),)
    )


def _snapshot(price: Decimal) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(AT, (ExactExecutionRow(AT, NAME, True, price),), (), (), ())


def test_the_default_settings_are_the_docstrings_claim_as_data() -> None:
    venue = KrxExchange([NAME])

    assert venue.settings == {
        "profile": "krx",
        "quantity_unit": "share",
        "commission_rate": str(COMMISSION_RATE),
        "sale_tax_rate": str(SALE_TAX_RATE),
        "price_limits": False,
        "short_sales": "refused",
        "partial_fills": "cash-limited",
        "not_modelled": list(KRX_NOT_MODELLED),
    }
    assert normalize_memory(dict(venue.settings)) == venue.settings, "strict JSON, as recorded"
    assert AcademicExchange({}).settings == {
        "profile": "academic",
        "costs": "none",
        "partial_fills": "never",
    }


def test_a_tax_free_krx_charges_no_tax_and_says_so() -> None:
    """The switch is the venue's; the fill and the record agree about it."""
    taxed = KrxExchange([NAME])
    untaxed = KrxExchange([NAME], sale_tax_rate="0")
    account = AccountSnapshot(0, Decimal("0"), {NAME: Decimal("10")})
    price = Decimal("1000")

    charged = taxed.execute(
        execution_call(taxed, _sell(Decimal("10"), price), account, _snapshot(price), registry=ROSTER)
    ).fills[0]
    exempt = untaxed.execute(
        execution_call(untaxed, _sell(Decimal("10"), price), account, _snapshot(price), registry=ROSTER)
    ).fills[0]

    assert charged.cost.tax == Decimal("10") * price * SALE_TAX_RATE
    assert exempt.cost.tax == Decimal("0")
    assert charged.cost.commission == exempt.cost.commission == Decimal("10") * price * COMMISSION_RATE
    assert untaxed.settings["sale_tax_rate"] == "0" and taxed.settings["sale_tax_rate"] == "0.002"


def test_rates_come_as_decimals_from_code_and_strings_from_config() -> None:
    assert KrxSettings.of("0.0003", Decimal("0")) == KrxSettings(COMMISSION_RATE, Decimal("0"))
    with pytest.raises(TypeError, match="decimal string"):
        KrxSettings.of(0.0003, "0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        KrxSettings.of("-0.1", "0")
    with pytest.raises(ValueError, match="not a valid decimal"):
        KrxExchange([NAME], commission_rate="three basis points")


def test_price_limits_are_a_listing_fact_reported_from_the_rules() -> None:
    """Bare ids take the band per `price_limits`; explicit rules carry their own and the switch
    must then be left alone -- one source of truth, reported as the venue actually has it."""
    off = KrxExchange([NAME])
    on = KrxExchange([NAME], price_limits=True)
    explicit = KrxExchange(krx_listings([NAME], price_limits=True))

    assert off.settings["price_limits"] is False and off.execution_requirements() == ()
    assert on.settings["price_limits"] is True and on.execution_requirements()
    assert explicit.settings["price_limits"] is True
    with pytest.raises(ValueError, match="decided by the listings"):
        KrxExchange(krx_listings([NAME]), price_limits=True)


def test_the_loader_refuses_a_venue_whose_settings_cannot_be_recorded(tmp_path: Path) -> None:
    path = tmp_path / "venue.py"
    path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import KrxExchange\n"
        "class Venue(KrxExchange):\n"
        "    def __init__(self):\n"
        f"        super().__init__([{NAME!r}])\n"
        "    @property\n"
        "    def settings(self):\n"
        "        return {'sale_tax_rate': Decimal('0.002')}\n",
        encoding="utf-8",
    )
    ref = ComponentRef.of(
        "venue",
        ComponentKind.EXCHANGE,
        path,
        "Venue",
        fingerprint=fingerprint_component(path, kind=ComponentKind.EXCHANGE, object_name="Venue"),
    )

    with pytest.raises(Exception) as caught:
        load_exchange(ref, project_root=tmp_path)

    failure = caught.value.failures[0]  # type: ignore[attr-defined]
    assert failure.code == "component.execution_profile_invalid"
    assert "settings must be a portable mapping" in failure.requirement


def test_a_registered_config_sets_the_rates(tmp_path: Path) -> None:
    """The same file, two configs: two venues that charge differently and say so."""
    path = tmp_path / "venue.py"
    path.write_text(
        "from vqapr.public import KrxExchange\n"
        "class Venue(KrxExchange):\n"
        "    def __init__(self, *, sale_tax_rate='0.002'):\n"
        f"        super().__init__([{NAME!r}], 'venue', sale_tax_rate=sale_tax_rate)\n",
        encoding="utf-8",
    )

    def loaded(config: dict[str, object]) -> KrxExchange:
        ref = ComponentRef.of(
            "venue",
            ComponentKind.EXCHANGE,
            path,
            "Venue",
            config=config,
            fingerprint=fingerprint_component(
                path, kind=ComponentKind.EXCHANGE, object_name="Venue", config=config
            ),
        )
        venue = load_exchange(ref, project_root=tmp_path)
        assert isinstance(venue, KrxExchange)
        return venue

    assert loaded({}).settings["sale_tax_rate"] == "0.002"
    assert loaded({"sale_tax_rate": "0"}).settings["sale_tax_rate"] == "0"
