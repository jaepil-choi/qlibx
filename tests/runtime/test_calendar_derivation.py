from datetime import date, time

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.runtime.calendar_derivation import (
    CalendarDerivationKind,
    CalendarDerivationRule,
    CalendarLimitation,
    derive_calendar,
)


def test_same_frozen_inputs_produce_the_same_calendar() -> None:
    rule = CalendarDerivationRule.all_instrument_date_union()

    first = derive_calendar(
        [date(2024, 3, 6), date(2024, 3, 5), date(2024, 3, 5)],
        rule=rule,
        timezone="Asia/Seoul",
        session_close=time(15, 30),
    )
    second = derive_calendar(
        [date(2024, 3, 5), date(2024, 3, 6)],
        rule=rule,
        timezone="Asia/Seoul",
        session_close=time(15, 30),
    )

    assert first == second
    assert first.calendar.sessions == (date(2024, 3, 5), date(2024, 3, 6))
    assert first.limitations == (CalendarLimitation.OBSERVED_UNION_DEFINES_SESSIONS,)


def test_reference_rule_records_its_economic_risk_and_identity() -> None:
    rule = CalendarDerivationRule.reference_instrument("005930")

    result = derive_calendar(
        [date(2024, 3, 5)],
        rule=rule,
        timezone="Asia/Seoul",
        session_close=time(15, 30),
    )

    assert result.rule.kind is CalendarDerivationKind.REFERENCE_INSTRUMENT_DATES
    assert result.rule.selector == "005930"
    assert result.limitations == (CalendarLimitation.REFERENCE_MISSING_REMOVES_SESSION,)


def test_index_rule_requires_the_selected_series_identity() -> None:
    with pytest.raises(ValueError, match="selector"):
        CalendarDerivationRule(CalendarDerivationKind.INDEX_SERIES_DATES)


def test_empty_derived_dates_fail_without_mutation_and_are_machine_readable() -> None:
    with pytest.raises(VqaprError) as caught:
        derive_calendar(
            [],
            rule=CalendarDerivationRule.all_instrument_date_union(),
            timezone="Asia/Seoul",
            session_close=time(15, 30),
        )

    payload = caught.value.as_dict()
    assert payload["stage"] == "calendar.derive"
    assert payload["family"] == "CALENDAR"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "calendar.derive.empty"


def test_invalid_date_values_are_bounded_in_a_structured_failure() -> None:
    with pytest.raises(VqaprError) as caught:
        derive_calendar(
            [date(2024, 3, 5), "2024-03-06"],  # type: ignore[list-item]
            rule=CalendarDerivationRule.all_instrument_date_union(),
            timezone="Asia/Seoul",
            session_close=time(15, 30),
        )

    assert caught.value.failures[0].code == "calendar.derive.invalid_date"
    assert caught.value.failures[0].example_total == 1
