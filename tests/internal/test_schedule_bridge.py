"""Translating a public Schedule into the engine's agendas.

A run decides on one cadence and values its book on another, so each role gets its own
agenda. The case worth pinning is the explicit absence: `monitoring=None` must produce no
monitoring agenda, rather than quietly inheriting one.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from vqapr._internal.schedule_bridge import agenda_for_cadence, agendas_for_schedule
from vqapr.simulation import Cadence, Schedule

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6))


def _cadence(at: time = time(16, 0)) -> Cadence:
    return Cadence(sessions=SESSIONS, at=at, timezone="Asia/Seoul")


def _schedule(monitoring: Cadence | None = None) -> Schedule:
    return Schedule(
        strategy=_cadence(),
        valuation=_cadence(time(15, 30)),
        monitoring=monitoring,
        start=datetime(2024, 3, 4, tzinfo=KST),
        end=datetime(2024, 3, 6, 23, tzinfo=KST),
    )


def test_each_role_gets_its_own_agenda():
    agendas = agendas_for_schedule(_schedule(), prefix="run")
    assert sorted(agendas) == ["strategy", "valuation"]
    assert agendas["strategy"].role.name == "STRATEGY_CALLBACK"
    assert agendas["valuation"].role.name == "VALUATION"


def test_one_occurrence_per_declared_session():
    agendas = agendas_for_schedule(_schedule(), prefix="run")
    assert len(agendas["strategy"].occurrences) == len(SESSIONS)
    assert len(agendas["valuation"].occurrences) == len(SESSIONS)


def test_explicit_absence_produces_no_monitoring_agenda():
    """`monitoring=None` is a declaration, not a gap to fill with a default."""
    agendas = agendas_for_schedule(_schedule(monitoring=None), prefix="run")
    assert "monitoring" not in agendas


def test_a_declared_monitoring_cadence_produces_its_agenda():
    agendas = agendas_for_schedule(_schedule(monitoring=_cadence(time(17, 0))), prefix="run")
    assert "monitoring" in agendas
    assert agendas["monitoring"].role.name == "MONITORING"
    assert len(agendas["monitoring"].occurrences) == len(SESSIONS)


def test_agenda_ids_are_prefixed_per_run():
    agendas = agendas_for_schedule(_schedule(), prefix="factor-hml")
    assert str(agendas["strategy"].agenda_id) == "factor-hml-strategy"
    assert str(agendas["valuation"].agenda_id) == "factor-hml-valuation"


def test_strategy_and_valuation_keep_their_own_wall_times():
    """A run values where it executes; the two cadences are not interchangeable."""
    agendas = agendas_for_schedule(_schedule(), prefix="run")
    strategy_instants = {o.local_instant for o in agendas["strategy"].occurrences}
    valuation_instants = {o.local_instant for o in agendas["valuation"].occurrences}
    assert strategy_instants != valuation_instants


def test_the_declaration_itself_refuses_an_empty_cadence():
    """Refused at construction, so the bridge never receives a sessionless cadence."""
    with pytest.raises(ValueError, match="at least one entry"):
        Cadence(sessions=(), at=time(16, 0), timezone="Asia/Seoul")


def test_a_missing_cadence_is_refused():
    with pytest.raises(ValueError, match="must not be None"):
        agenda_for_cadence(None, agenda_id="run-strategy", role=None)


def test_an_empty_prefix_is_refused():
    with pytest.raises(ValueError, match="prefix must be a non-empty string"):
        agendas_for_schedule(_schedule(), prefix="")
