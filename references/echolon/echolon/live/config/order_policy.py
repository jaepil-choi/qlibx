"""Order-routing policy constants.

Single source of truth for tunable order-placement knobs.

Calibration history:
- 2026-05-07: initial values from order-routing redesign (defensive
  defaults, not data-driven).
- 2026-05-08 followup F5: tightened slippage caps + circuit breaker
  rates after edge analysis showed original 2%/5% caps exceeded typical
  per-trade strategy edge (~0.15-0.25%) by ~10x. New values aim for the
  cap to be ≤ 1× typical edge for ENTRY and ≤ 4× ATR for EXIT.

Rationale for ``BUFFER_TICKS_BY_ATTEMPT[1] = 4``:
    Yesterday's al_s1 ENTRY_SHORT bug (2026-05-06 21:00:07) submitted
    FIX_PRICE @ bid1=24645 with zero buffer. The market moved through
    24645 within seconds and never returned. A 4-tick buffer (20 CNY for
    al, price_tick=5) keeps the order marketable for the first ~60s of
    the night session.

Buffer / slippage-cap interaction (ENTRY at 0.20% cap):
    The cumulative-drift slippage cap (``MAX_SLIPPAGE_PCT_BY_CLASS``)
    is pinned to the strategy-decision price across the whole retry
    chain. Each retry's buffer counts toward the cap. The cap clips
    the chain when ``buffer_ticks_at_attempt_N * price_tick / price``
    exceeds the cap. With buffer ladder {1: 4, 2: 8, 3: 16}:

      | slot       | att-1 buf % | att-2 buf % | att-3 buf % | effective chain                   |
      | al @ 24600 | 0.081%      | 0.163%      | 0.325%      | 2 attempts (att-3 buffer > cap)   |
      | cu @ 80000 | 0.050%      | 0.100%      | 0.200%      | 2-3 attempts (att-3 == cap edge)  |
      | zn @ 22000 | 0.091%      | 0.182%      | 0.364%      | 2 attempts (att-3 buffer > cap)   |

    The ENTRY cap is the binding constraint: for al and zn, attempt 3's
    16-tick buffer alone exceeds the 0.20% cap regardless of market
    drift, so the chain is de-facto a 2-attempt sequence on those slots.
    That's intended — if 12 cumulative ticks of aggressive buffer over
    60 seconds don't fill, the market has moved enough that abandoning
    the entry is the right call. Attempt 3 (16 ticks) is reserved for
    EXIT-class chains, where the wider 0.80% cap does fit it.

    For ENTRY-class on cu, attempt 3's percentage equals the cap
    exactly (0.200% == 0.0020); any market drift trips it. Effectively
    2.5 attempts depending on tick movement at decision time.

    EXIT cap (0.80%) accommodates the full 5-attempt chain for all
    configured non-ferrous slots (max att-3 buffer = 0.36% << 0.80%).
"""

from typing import Dict


# ----- Layer 1 — Tick buffer ------------------------------------------------

BUFFER_TICKS_BY_ATTEMPT: Dict[int, int] = {1: 4, 2: 8, 3: 16}
DEFAULT_BUFFER_TICKS: int = 4


# ----- Layer 2 — Watchdog timing --------------------------------------------

WATCHDOG_TICK_S: float = 0.1            # main loop polling cadence
QUIESCENCE_WINDOW_S: float = 1.5        # WINDING_DOWN -> TERMINAL after this gap
DEADLINE_DEFAULT_S: float = 30.0        # cancel-and-resubmit after this idle
TICK_SNAPSHOT_MAX_AGE_S: float = 4.0    # tick freshness threshold (was 2.0; off-peak ticks routinely 3-5s old on SHFE)


# ----- Layer 2 — Resubmit policy by recovery class --------------------------

MAX_ATTEMPTS_BY_CLASS: Dict[str, int] = {
    "ENTRY": 3,
    "EXIT": 5,
    "ROLLOVER_OPEN": 3,
    "ROLLOVER_CLOSE": 5,
    "FORCED_EXIT": 5,
}

# Cumulative-drift slippage cap per recovery class. Pinned to
# intended_price across the entire retry chain (Amendment E). When this
# cap is exceeded by a candidate resubmit price, the chain abandons
# rather than chasing.
#
# Tuning principle: cap ≤ 1× typical per-trade strategy edge for ENTRY,
# ≤ 4× daily ATR for EXIT (Amendment B's kill-at-band-edge handles
# trapped positions in cycle 3+, so EXIT cap need not be wide).
#
# 2026-05-08 followup F5: lowered from {ENTRY: 0.02, EXIT: 0.05, ...}
# which exceeded typical strategy edge of 0.15-0.25% by ~10x.
MAX_SLIPPAGE_PCT_BY_CLASS: Dict[str, float] = {
    "ENTRY": 0.0020,         # was 0.02; ~49 CNY for al @ 24600 = ~10 ticks
    "EXIT": 0.0080,          # was 0.05; relies on Amendment B for trapped
    "ROLLOVER_OPEN": 0.0020, # was 0.02
    "ROLLOVER_CLOSE": 0.0080,# was 0.05
    "FORCED_EXIT": 0.0150,   # was 0.05; widest because already-forced
}


# ----- Amendment G — Circuit breaker ----------------------------------------

# Per-cycle execution-quality thresholds. Tripping the circuit refuses
# new submissions until operator reset.
#
# 2026-05-08 followup F5: tightened from {abandoned_pct: 0.4,
# rejected_pct: 0.5, min_n: 5}. A 40% abandon or 50% rejection rate is
# already a catastrophe by the time it trips — the new values fire
# earlier, leaving margin for operator triage before more capital is
# committed to a broken pipe.
CIRCUIT_THRESHOLDS: Dict[str, float] = {
    "consecutive_abandoned": 2,
    "abandoned_rate_min_n": 10,    # was 5; more stable rate against small-sample noise
    "abandoned_rate_pct": 0.20,    # was 0.4; 20% abandon rate is alarming
    "rejected_rate_pct": 0.25,     # was 0.5; 25% rejection rate is clearly broken
    "late_trade_count": 3,
}


# ----- Amendment B — Kill-at-band-edge --------------------------------------

KILL_BAND_FRACTION: float = 0.85         # 85% of the way to the band
DAILY_BAND_SAFETY_MARGIN: float = 0.01   # 1% inside the band


# ----- Layer 4 — Splitter ---------------------------------------------------

MIN_PARTIAL_FILL_FRACTION: float = 0.5   # threshold for sequential-with-confirm
