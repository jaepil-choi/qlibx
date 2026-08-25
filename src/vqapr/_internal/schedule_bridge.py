"""Turn a public `Schedule` into the engine's registered agendas.

A `Cadence` is a set of sessions, a venue-local wall time and a timezone. That is exactly
what `OperationAgenda.daily` takes, so the translation is direct rather than clever: one
agenda per role, built from the cadence the caller declared.

The role split is the substance here. A run values its book where it executes and decides
on its own cadence, so strategy, valuation and monitoring each get their own agenda. A
schedule that declares `monitoring=None` gets no monitoring agenda at all - the explicit
absence the public contract requires, carried through rather than silently replaced by a
default cadence nobody asked for.
"""

from __future__ import annotations

from typing import Any

__all__ = ("agenda_for_cadence", "agendas_for_schedule")


def agenda_for_cadence(cadence: Any, *, agenda_id: str, role: Any) -> Any:
    """Build one engine agenda from one public cadence."""
    from vqapr.public import OperationAgenda

    if cadence is None:
        raise ValueError("cadence must not be None")
    return OperationAgenda.daily(
        agenda_id=agenda_id,
        role=role,
        sessions=cadence.sessions,
        at=cadence.at,
        timezone=cadence.timezone,
        provenance=f"declared:{agenda_id}",
    )


def agendas_for_schedule(schedule: Any, *, prefix: str) -> dict[str, Any]:
    """Build every agenda a schedule implies, keyed by role name.

    Returns `strategy` and `valuation` always, and `monitoring` only when the schedule
    declared one. A caller inspecting the result can therefore tell the difference between
    "monitoring at this cadence" and "explicitly no monitoring", which is the distinction
    the public `monitoring: Cadence | None` field exists to express.
    """
    from vqapr.public import OperationRole

    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")

    agendas = {
        "strategy": agenda_for_cadence(
            schedule.strategy,
            agenda_id=f"{prefix}-strategy",
            role=OperationRole.STRATEGY_CALLBACK,
        ),
        "valuation": agenda_for_cadence(
            schedule.valuation,
            agenda_id=f"{prefix}-valuation",
            role=OperationRole.VALUATION,
        ),
    }
    if schedule.monitoring is not None:
        agendas["monitoring"] = agenda_for_cadence(
            schedule.monitoring,
            agenda_id=f"{prefix}-monitoring",
            role=OperationRole.MONITORING,
        )
    return agendas
