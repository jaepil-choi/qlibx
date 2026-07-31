"""Sanity tests for order_policy constants — guard against accidental
relaxation that would expose the trader to excessive slippage.

These tests assert specific bounds, not exact values. If you intend to
change a constant, update both the constant AND the bound here, with a
comment explaining why."""
from echolon.live.config import order_policy as op


# ---- Slippage caps must not exceed strategy edge magnitude ----

def test_entry_slippage_cap_is_tight():
    """ENTRY cap should not exceed 0.30%. Typical SHFE non-ferrous
    daily-strategy per-trade edge is 0.15-0.25%; an entry filled more
    than 0.30% offside has already lost the trade's expected edge."""
    assert op.MAX_SLIPPAGE_PCT_BY_CLASS["ENTRY"] <= 0.0030
    assert op.MAX_SLIPPAGE_PCT_BY_CLASS["ROLLOVER_OPEN"] <= 0.0030


def test_exit_slippage_cap_is_reasonable():
    """EXIT cap should not exceed 1.5% (well inside 7% non-ferrous band).
    Amendment B's kill-at-band-edge handles trapped positions at cycle
    3+; the per-cycle EXIT cap need not be wide."""
    assert op.MAX_SLIPPAGE_PCT_BY_CLASS["EXIT"] <= 0.015
    assert op.MAX_SLIPPAGE_PCT_BY_CLASS["ROLLOVER_CLOSE"] <= 0.015


def test_forced_exit_cap_does_not_exceed_band():
    """FORCED_EXIT may be wider but must stay safely inside the
    non-ferrous daily band (7%) less the BandGuard safety margin."""
    assert op.MAX_SLIPPAGE_PCT_BY_CLASS["FORCED_EXIT"] <= 0.030


# ---- Circuit breaker must trip before catastrophic failure rates ----

def test_circuit_abandoned_rate_threshold_is_strict():
    """Abandon rate threshold must be ≤ 25%. Above that the circuit is
    only tripping AFTER significant capital has been committed to a
    broken pipeline."""
    assert op.CIRCUIT_THRESHOLDS["abandoned_rate_pct"] <= 0.25


def test_circuit_rejected_rate_threshold_is_strict():
    """Rejected rate threshold must be ≤ 30%. A 50% rejection rate is
    a broken pipeline, not a marginal degradation."""
    assert op.CIRCUIT_THRESHOLDS["rejected_rate_pct"] <= 0.30


def test_circuit_consecutive_abandoned_is_low():
    """Two consecutive abandons must trip — back-to-back ENTRY failures
    indicate structural issue, not transient noise."""
    assert op.CIRCUIT_THRESHOLDS["consecutive_abandoned"] <= 2


# ---- Buffer ladder must escalate ----

def test_buffer_ladder_is_monotonic():
    """Each retry attempt's buffer must be ≥ the previous attempt's."""
    buffers = op.BUFFER_TICKS_BY_ATTEMPT
    assert buffers[1] <= buffers[2] <= buffers[3]


def test_buffer_ladder_first_attempt_nonzero():
    """The whole point of the buffer ladder is the first attempt's
    buffer being non-zero (regression guard against the 2026-05-06 bug)."""
    assert op.BUFFER_TICKS_BY_ATTEMPT[1] >= 1


# ---- Tick freshness threshold tolerates off-peak SHFE ticks ----

def test_tick_freshness_threshold_tolerates_offpeak():
    """SHFE ticks during quiet periods (lunch break / pre-close) routinely
    show 3-5 second gaps; the freshness threshold must accommodate these
    or Tier 1 pricing will fall through too aggressively."""
    assert op.TICK_SNAPSHOT_MAX_AGE_S >= 3.0


# ---- Sanity: kill-band fraction stays inside actual band ----

def test_kill_band_fraction_stays_below_actual_band():
    """KILL_BAND_FRACTION × band_pct must leave a safety margin against
    the exchange-rejection band."""
    # Combined effect: 0.85 of band - 0.01 safety = 0.84 of band
    effective = op.KILL_BAND_FRACTION
    assert effective <= 0.95  # never within 5% of actual band
    assert op.DAILY_BAND_SAFETY_MARGIN >= 0.005


# ---- Resubmit attempts asymmetry: EXIT must allow more than ENTRY ----

def test_exit_allows_more_attempts_than_entry():
    """EXIT classes (with a position to close) must allow more retries
    than ENTRY (which can be abandoned)."""
    a = op.MAX_ATTEMPTS_BY_CLASS
    assert a["EXIT"] >= a["ENTRY"]
    assert a["ROLLOVER_CLOSE"] >= a["ROLLOVER_OPEN"]
    assert a["FORCED_EXIT"] >= a["ENTRY"]
