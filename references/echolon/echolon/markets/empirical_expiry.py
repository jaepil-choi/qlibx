"""Episode-keyed empirical futures last-trade lookup.

The bundled table is derived offline from the p2_v4 contract panel. Rows with
the same contract identifier are split whenever adjacent observations are more
than 180 calendar days apart. This is essential for CZCE's decade-repeating
three-digit identifiers.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files


@dataclass(frozen=True)
class EmpiricalEpisode:
    """One expired listing episode observed in the authoritative panel."""

    exchange: str
    contract: str
    first_observation: dt.date
    last_trade: dt.date


def empirical_last_trade(contract: str, asof: dt.date) -> dt.date | None:
    """Return the episode active at, or nearest before, ``asof``.

    Only expired episodes are bundled. ``None`` means no expired episode starts
    on or before ``asof``; callers may then use a validated live-contract rule.
    """
    episode = empirical_episode(contract, asof)
    return episode.last_trade if episode is not None else None


def empirical_episode(contract: str, asof: dt.date) -> EmpiricalEpisode | None:
    """Return the episode record active at, or nearest before, ``asof``."""
    normalized = contract.strip().upper()
    candidates = [
        episode
        for episode in _episodes_by_contract().get(normalized, ())
        if episode.first_observation <= asof
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda episode: episode.first_observation)


def empirical_episodes(contract: str) -> tuple[EmpiricalEpisode, ...]:
    """Expose immutable episode records for audit and validation."""
    return _episodes_by_contract().get(contract.strip().upper(), ())


@lru_cache(maxsize=1)
def _episodes_by_contract() -> dict[str, tuple[EmpiricalEpisode, ...]]:
    path = files("echolon.markets").joinpath("data/empirical_last_trades.csv")
    grouped: dict[str, list[EmpiricalEpisode]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            episode = EmpiricalEpisode(
                exchange=row["exchange"],
                contract=row["contract"],
                first_observation=dt.date.fromisoformat(row["first_observation"]),
                last_trade=dt.date.fromisoformat(row["last_trade"]),
            )
            grouped.setdefault(episode.contract, []).append(episode)
    return {
        contract: tuple(sorted(episodes, key=lambda item: item.first_observation))
        for contract, episodes in grouped.items()
    }
