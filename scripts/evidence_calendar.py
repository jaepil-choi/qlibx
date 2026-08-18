"""Runtime calendar core evidence.

Run with::

    uv run python scripts/evidence_calendar.py

The payload is intentionally JSON so an agent can compare it across runs.
"""

from __future__ import annotations

import json
from datetime import date, time

from vqapr.runtime.calendar_derivation import CalendarDerivationRule, derive_calendar
from vqapr.runtime.timeline import Timeline

from vqapr.runtime.events import Event, EventKind


def main() -> None:
    union_rule = CalendarDerivationRule.all_instrument_date_union()
    union = derive_calendar(
        [date(2024, 3, 6), date(2024, 3, 5), date(2024, 3, 7), date(2024, 3, 5)],
        rule=union_rule,
        timezone="Asia/Seoul",
        session_open=time(9, 0),
        session_close=time(15, 30),
    )
    union_again = derive_calendar(
        [date(2024, 3, 7), date(2024, 3, 5), date(2024, 3, 6)],
        rule=union_rule,
        timezone="Asia/Seoul",
        session_open=time(9, 0),
        session_close=time(15, 30),
    )
    reference = derive_calendar(
        [date(2024, 3, 5), date(2024, 3, 7)],
        rule=CalendarDerivationRule.reference_instrument("REFERENCE_HALTED_ON_2024-03-06"),
        timezone="Asia/Seoul",
        session_close=time(15, 30),
    )

    session = date(2024, 3, 6)
    decision = Event(union.calendar.at(session, time(4, 0)), EventKind.DECISION, session)
    close = union.calendar.close_at(session)
    shuffled = [
        Event(close, EventKind.FINALIZE, session),
        Event(close, EventKind.VALUATION, session),
        Event(close, EventKind.FILL_COMMIT, session),
        Event(close, EventKind.EXECUTION, session),
        decision,
        Event(close, EventKind.MONITORING, session),
    ]
    timeline = Timeline.of(shuffled)

    payload = {
        "calendar": {
            "union": {
                "rule": union.rule.kind,
                "sessions": [day.isoformat() for day in union.calendar],
                "session_open": union.calendar.session_open.isoformat(),
                "session_close": union.calendar.session_close.isoformat(),
                "timezone": union.calendar.timezone,
                "limitations": list(union.limitations),
            },
            "reference": {
                "rule": reference.rule.kind,
                "selector": reference.rule.selector,
                "sessions": [day.isoformat() for day in reference.calendar],
                "limitations": list(reference.limitations),
            },
            "same_dates_different_input_order_equal": union == union_again,
            "reference_rule_lost_2024_03_06": session not in reference.calendar,
        },
        "timeline": {
            "constructed_without_data_rows": True,
            "data_available_is_event_kind": "DATA_AVAILABLE" in EventKind.__members__,
            "events": [
                {
                    "ts": event.ts.isoformat(),
                    "kind": event.kind,
                    "session": event.session.isoformat(),
                }
                for event in timeline
            ],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
