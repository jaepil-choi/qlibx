from __future__ import annotations

from pathlib import Path

from qlib_extended.research import load_market_cohort_contract


ROOT = Path(__file__).resolve().parents[1]


def test_market_family_members_share_exact_order_calendar() -> None:
    contract = load_market_cohort_contract(ROOT / "research" / "price")
    atom_by_name = {item["name"]: item for item in contract.atomic}

    assert len(contract.atomic) == 20
    assert {family["frequency_days"] for family in contract.families} == {1, 21}
    for family in contract.families:
        assert family["order_calendar_key"] != "mixed_frequency_research_only"
        assert all(
            atom_by_name[member]["order_calendar_key"]
            == family["order_calendar_key"]
            for member in family["members"]
        )
