# 085 — the fill summary counts reasons and never instruments, so a name that never filled at all is invisible

**Status:** **CLOSED 2026-09-05 -- record `156`.** `fill_summary` reports `never_filled`, one
entry per instrument ordered in the run and never dealt, with its order count and its most
frequent reason. The optional `check` warning is not built -- `check` has no advisory channel
and the payload is the fix. Ruling below, as filed.

**Ruling 2026-09-05 by owner: split the counter, same rule as `086`.** A
counter that folds two different facts is split, and the per-instrument fact goes in the success
payload: `never_filled: [{instrument, orders, dealt, reason}]`, an instrument ordered in the run
that never dealt once. Nothing failed, so this is a payload and not a refusal. `check` may warn --
warn, never refuse -- where `run.instruments - execution_input.instruments` is non-empty. `086`
carries the same ruling on the constraint side; the two are one rule seen twice.

**Status when filed:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (C5), whose
enhanced-index book carried a 20% ETF sleeve that never traded once across 82 rebalances. Confirmed
in source on this branch.

**Touches:** `src/vqapr/analysis/execution.py:19-65` (`fill_summary`: `orders`, `dealt`, `partial`,
`zero_dealt` and `reasons`, aggregated over rows and never over instruments).

## What happens

The reporter put `A069500` (KODEX 200) in the run's `instruments`, in the exchange listing and in
the roster, and left it out of the execution input's price table. Every rebalance ordered it and
every fill dealt zero — the correct outcome for a name with no price row. The run reported:

```
ok: true
reasons: {absent: N, no_trade: M, nontradable: K}
```

`absent: N` is one number. It does not distinguish **one missing row on each of 200 names** —
ordinary, and what a real market looks like — from **the same name missing 82 times in a row**,
which is a configuration error. Both fold into the same counter, so no threshold on it can ever
separate them.

The discovery path was: performance looks wrong → notice the shortfall (−4.45%p) matches the drag
of 20% of the book sitting in cash (0.2 × 22% ≈ 4.4%p) to the digit → open the fill table by hand →
count ETF rows → check the venue table. Thirty minutes, and every step of it happened because the
reporter already suspected something. Without the suspicion the conclusion is *"adding the sleeve
hurt performance"*.

## Why this is `039` again

`fill_summary` exists **because** of `039`, and its docstring tells that story: a market-neutral run
reported `ok: true` while 3.1% of its fills dealt nothing, and the one signal that would have
exposed it was reachable only by reading 47,318 rows by hand. The fix aggregated the reasons the
rows already carried.

This is the same defect one axis over. The framework behaved correctly and wrote down every fact —
an unfillable order leaving its cash in the account is exactly right, and `vqapr.fill` records the
`ZeroDealtReason` on every one of those 82 rows. What is missing is the aggregate, and it is one
`groupby` from the rows `fill_summary` already walks.

## What to do

**Add the per-instrument fact to the success payload**, not a refusal — nothing here failed:

```
never_filled: [{instrument: "A069500", orders: 82, dealt: 0, reason: "absent"}]
```

An instrument that was ordered in a run and never dealt once is a statement `fill_summary` can make
in the loop it already runs, and it cannot be produced by ordinary market behaviour at any length
of run. A `partial`-style count per instrument would also serve, but the never-filled case is the
one that is unambiguous.

**Secondarily**, `vqapr check` could warn — warn, not refuse — where
`run.instruments − execution_input.instruments` is non-empty. It has to be a warning: a name in the
universe that is simply not listed during the period is a legitimate configuration, which is why
this cannot become a gate.

## Related

`039` (the aggregate this one is missing an axis of), `051` (a record reporting nothing about what
it declared), `086` (the other counter that folds two different facts together), record `114` (where
`fill_summary` came from).
