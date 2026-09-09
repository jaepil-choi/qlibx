from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from vqapr.domain.agendas import OperationAgenda, OperationOccurrence
from vqapr.domain.identifiers import agenda_id, occurrence_id
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.flow.engine.loop import MarketEvent, OccurrenceEvent


def _local(
    *,
    day: date = date(2024, 3, 6),
    wall_time: time = time(4, 0),
    timezone: str = "Asia/Seoul",
    fold: int = 0,
    offset: str = "+09:00",
) -> LocalInstantDeclaration:
    return LocalInstantDeclaration(day, wall_time, timezone, fold, offset)


def _occurrence(identifier: str) -> OperationOccurrence:
    return OperationOccurrence(occurrence_id(identifier), _local())


def _agenda(*occurrences: OperationOccurrence) -> OperationAgenda:
    return OperationAgenda(
        agenda_id=agenda_id("strategy"),
        timezone="Asia/Seoul",
        occurrences=occurrences,
    )


def test_local_instant_proves_an_ambiguous_fold_and_offset() -> None:
    declaration = _local(
        day=date(2024, 11, 3),
        wall_time=time(1, 30),
        timezone="America/New_York",
        fold=1,
        offset="-05:00",
    )

    assert declaration.utc_instant == datetime(2024, 11, 3, 6, 30, tzinfo=UTC)
    assert declaration.identity() == ("2024-11-03", "01:30:00", "America/New_York", 1, "-05:00")


@pytest.mark.parametrize(
    "declaration",
    [
        lambda: _local(
            day=date(2024, 3, 10),
            wall_time=time(2, 30),
            timezone="America/New_York",
            offset="-05:00",
        ),
        lambda: _local(
            day=date(2024, 11, 3),
            wall_time=time(1, 30),
            timezone="America/New_York",
            fold=1,
            offset="-04:00",
        ),
        lambda: _local(fold=1),
    ],
)
def test_local_instant_rejects_gap_or_inconsistent_resolution_proof(declaration: object) -> None:
    with pytest.raises(ValueError):
        declaration()  # type: ignore[operator]


def test_agenda_uses_stable_ids_to_order_same_instant() -> None:
    agenda = _agenda(_occurrence("z"), _occurrence("a"))

    assert [occurrence.occurrence_id for occurrence in agenda.occurrences] == ["a", "z"]
    assert agenda.occurrences[0].utc_evaluation_time == agenda.occurrences[1].utc_evaluation_time


def test_agenda_rejects_duplicate_occurrence_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        _agenda(_occurrence("same"), _occurrence("same"))


def test_agenda_slice_is_inclusive_and_can_be_empty() -> None:
    agenda = _agenda(_occurrence("one"))
    instant = agenda.occurrences[0].utc_evaluation_time

    assert agenda.inclusive_slice(instant, instant) == agenda.occurrences
    assert (
        agenda.inclusive_slice(datetime(2024, 3, 7, tzinfo=UTC), datetime(2024, 3, 8, tzinfo=UTC))
        == ()
    )


def test_cross_zone_occurrences_share_the_same_canonical_utc_instant() -> None:
    seoul = OperationOccurrence(occurrence_id("seoul"), _local())
    new_york = OperationOccurrence(
        occurrence_id("new-york"),
        _local(
            day=date(2024, 3, 5),
            wall_time=time(14, 0),
            timezone="America/New_York",
            offset="-05:00",
        ),
    )

    assert seoul.utc_evaluation_time == new_york.utc_evaluation_time
    assert seoul.sort_key()[0] == new_york.sort_key()[0]


def test_a_market_instant_sorts_before_a_same_time_decision() -> None:
    """Design §3.1: what was decided earlier fills and is valued before anything new decides."""
    occurrence = _occurrence("callback")
    operation = OccurrenceEvent(occurrence)
    market = MarketEvent(occurrence.evaluation_time)

    assert sorted((operation, market), key=lambda item: item.sort_key()) == [market, operation]
