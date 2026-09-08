"""Building an agenda from the sessions a dataset actually has.

The constructor takes occurrences that are already known. The common case is not a list: it is
"every session this registered dataset has, at 08:00 local".
Turning one into the other is mechanical, and it was being written by hand at every call site --
three copies of the same sixteen lines, each of which owned the occurrence id scheme and the DST
constants.

What those copies got to decide is what these tests pin down.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from vqapr.domain.agendas import OperationAgenda, OperationRole

SEOUL = "Asia/Seoul"
NEW_YORK = "America/New_York"
AT = time(8, 0)


def _daily(sessions, timezone=SEOUL, at=AT, agenda_id="alpha") -> OperationAgenda:
    return OperationAgenda.daily(
        agenda_id=agenda_id,
        role=OperationRole.STRATEGY_CALLBACK,
        sessions=sessions,
        at=at,
        timezone=timezone,
    )


def test_one_occurrence_per_session_at_the_declared_local_time() -> None:
    agenda = _daily([date(2024, 3, 5), date(2024, 3, 6)])

    assert [o.occurrence_id for o in agenda.occurrences] == [
        "alpha-2024-03-05",
        "alpha-2024-03-06",
    ]
    # 08:00 Seoul is 23:00 UTC the previous day.
    assert agenda.occurrences[0].utc_evaluation_time == datetime(2024, 3, 4, 23, tzinfo=UTC)


def test_sessions_may_be_the_timestamps_a_dataset_reports() -> None:
    """`Workspace.evaluation_times` returns instants, so they pass straight through.

    Only the venue-local date is taken from them. When a row became available and when a decision
    is made are different facts, which is why `at` is separate.
    """
    available_at = [datetime(2024, 3, 5, 6, 30, tzinfo=UTC)]

    agenda = _daily(available_at)

    assert [o.occurrence_id for o in agenda.occurrences] == ["alpha-2024-03-05"]
    assert agenda.occurrences[0].utc_evaluation_time == datetime(2024, 3, 4, 23, tzinfo=UTC)


def test_many_rows_on_one_day_produce_one_occurrence() -> None:
    """A dataset can carry several rows per session; the agenda takes the day once."""
    same_day = [
        datetime(2024, 3, 5, 1, tzinfo=UTC),
        datetime(2024, 3, 5, 6, 30, tzinfo=UTC),
        datetime(2024, 3, 5, 9, tzinfo=UTC),
    ]

    assert len(_daily(same_day).occurrences) == 1


def test_sessions_are_ordered_however_they_arrive() -> None:
    agenda = _daily([date(2024, 3, 7), date(2024, 3, 5), date(2024, 3, 6)])

    assert [o.occurrence_id for o in agenda.occurrences] == [
        "alpha-2024-03-05",
        "alpha-2024-03-06",
        "alpha-2024-03-07",
    ]


def test_the_occurrence_id_is_the_frameworks_to_choose() -> None:
    """Two call sites inventing their own id schemes give one session two identities.

    A replay then stops being comparable to the run it replays, and nothing announces it.
    """
    first = _daily([date(2024, 3, 5)], agenda_id="alpha")
    again = _daily([date(2024, 3, 5)], agenda_id="alpha")

    assert first.occurrences[0].occurrence_id == again.occurrences[0].occurrence_id


def test_dst_offsets_are_derived_rather_than_typed() -> None:
    """A hand-written offset is right until the venue observes DST.

    New York is -05:00 in March and -04:00 in April. A constant is wrong on one of them and the
    declaration still validates on every other day of the year.
    """
    agenda = _daily([date(2024, 3, 1), date(2024, 4, 1)], timezone=NEW_YORK, at=time(9, 30))

    offsets = [o.local_instant.offset for o in agenda.occurrences]
    assert offsets == ["-05:00", "-04:00"]


def test_a_wall_time_that_does_not_exist_is_refused() -> None:
    """Spring forward: 02:30 never happens, so there is no instant to name."""
    with pytest.raises(ValueError, match="does not exist"):
        _daily([date(2024, 3, 10)], timezone=NEW_YORK, at=time(2, 30))


def test_a_wall_time_that_happens_twice_is_refused() -> None:
    """Fall back: 01:30 happens twice, and guessing would silently pick one."""
    with pytest.raises(ValueError, match="occurs twice"):
        _daily([date(2024, 11, 3)], timezone=NEW_YORK, at=time(1, 30))


def test_provenance_records_what_the_agenda_was_built_from() -> None:
    agenda = _daily([date(2024, 3, 5), date(2024, 3, 6)])

    assert agenda.provenance == f"2 sessions at {AT.isoformat()} {SEOUL}"


def test_an_explicit_provenance_survives() -> None:
    agenda = OperationAgenda.daily(
        agenda_id="alpha",
        role=OperationRole.STRATEGY_CALLBACK,
        sessions=[date(2024, 3, 5)],
        at=AT,
        timezone=SEOUL,
        provenance="k200 sessions from the registered price panel",
    )

    assert agenda.provenance == "k200 sessions from the registered price panel"
