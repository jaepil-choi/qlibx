"""Research-versus-implementation degradation reporting."""

from __future__ import annotations

from collections.abc import Mapping


def implementation_degradation(
    research_summary: Mapping[str, object],
    implementation_summary: Mapping[str, object],
) -> dict[str, float | None]:
    """Return the implementation/research net-Sharpe ratio without applying a bound.

    The summaries must contain numeric ``net_sharpe`` values. A zero research net
    Sharpe raises ``ValueError`` because its implementation ratio is undefined.
    """
    research_net_sharpe = float(research_summary["net_sharpe"])
    implementation_net_sharpe = float(implementation_summary["net_sharpe"])
    if research_net_sharpe == 0.0:
        raise ValueError("research net_sharpe must be non-zero")
    return {
        "research_net_sharpe": research_net_sharpe,
        "implementation_net_sharpe": implementation_net_sharpe,
        "ratio": implementation_net_sharpe / research_net_sharpe,
        "bound": None,
    }
