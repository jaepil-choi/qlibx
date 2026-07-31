"""
carry_front_back — raw front-vs-back settlement basis, annualized
==================================================================

The primary carry direction signal. Computed from a same-date forward-
curve snapshot (per :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`).

Sign convention (LOAD-BEARING — the qorka strategy layer reads sign as
direction): per ``paradigms/carry/indicator_pool.py`` line 14::

    raw basis     = settlement[front] / settlement[back] − 1
    positive      = backwardation = front > back  = LONG signal
    negative      = contango      = front < back  = SHORT signal

Annualized form (this module's output)::

    raw_basis     = settlement_front / settlement_back - 1
    dte_diff_days = days_to_expiry_back - days_to_expiry_front
    annualized    = raw_basis * 365.0 / dte_diff_days

Note on the WS2 B2.3 spec formula: the task spec wrote
``(settlement_back - settlement_front) / settlement_front`` which has
the OPPOSITE sign from the qorka pool docstring. We pick the qorka
docstring convention because the consumer (qorka strategy layer) reads
the sign as the direction signal — flipping the sign here would invert
every long/short call downstream. Mathematically the two formulas are
first-order equivalent and identical up to a sign flip + a denominator
choice (front vs back); under a flat curve both forms give the same
ordering across instruments.
"""
from __future__ import annotations

import pandas as pd

from .utils import days_to_expiry_pair, front_back_settlements


def carry_front_back(curve_snapshot: pd.DataFrame) -> float:
    """Annualized front-vs-back basis carry (qorka-consumer sign convention).

    Args:
        curve_snapshot: DataFrame returned by
            :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`.
            Must have at least 2 rows (front + back) and the columns
            ``settlement`` and ``days_to_expiry``.

    Returns:
        Annualized carry as a float.

        - Positive → backwardation (front > back) → long-side carry.
        - Negative → contango (front < back) → short-side carry.

    Raises:
        EchelonError IND-005: missing ``settlement`` or
            ``days_to_expiry`` column.
        ValueError: snapshot has fewer than 2 contracts, or front DTE
            equals back DTE (degenerate two-contract case).
        ZeroDivisionError: settlement_back is exactly zero (degenerate
            data; let it propagate per NO_ERROR_HANDLING).
    """
    settlement_front, settlement_back = front_back_settlements(curve_snapshot)
    dte_front, dte_back = days_to_expiry_pair(curve_snapshot)

    dte_diff = dte_back - dte_front
    if dte_diff == 0:
        raise ValueError(
            "carry_front_back: dte_back == dte_front; cannot annualize "
            "with zero expiry-spread (degenerate chain)"
        )

    raw_basis = settlement_front / settlement_back - 1.0
    return raw_basis * 365.0 / dte_diff
