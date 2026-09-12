# show_008 — Three signed alphas, a family ensemble, and a measured signal

```
reversal member  (Academic)  -> publish_run_allocation -> reversal_allocation
momentum member  (Academic)  -> publish_run_allocation -> momentum_allocation
low-vol member   (Academic)  -> publish_run_allocation -> lowvol_allocation
                                                                |
                                                                +--> ensemble run (KRX)
```

Reproduce:

```
uv run python showcases/show_008_alpha_family_ensemble/run.py
```

## What this adds over show_006

show_006 proved ensemble netting with **two** members. `UC-ENSEMBLE-001` is stated for "여러 stored
alpha-weight result", and two members cannot distinguish a helper that generalises from one that
happens to work in pairs. With three, `offset_weight = min(long, |short|)` stops being a restatement
of "the two disagreed": a name can be long in two members and short in one.

The low-volatility member is the reason this is a new showcase rather than an edit to show_006. It
is the first alpha in the tree whose signal is a rolling time-series statistic. Only its latest
trailing window is consumed, so the member computes that statistic directly with
`statistics.stdev` instead of wrapping it in a second rolling API.

## Results on the committed KRX fixture

| | |
|---|---|
| sessions / member callbacks / ensemble callbacks | 22 / 21 / 11 |
| reversal published | 16 events, 64 rows |
| momentum published | 11 events, 44 rows |
| low-vol published | 11 events, 44 rows |
| members netted | 3 |
| crossing events | 11 |
| max ticker `offset_weight` | 0.04 |
| split ticker-events | 38 |
| low-vol mean IC | **0.0162** over 10 scored events |
| rebalances | 11 |
| dealt fills | 20 (whole shares) |
| commission / sale tax | 71,784.69 / 199,170.20 |
| replayed cash == committed cash | 959,616,945.11 |
| final NAV | 999,165,945.11 (from 1,000,000,000) |
| any short position | False |

**The mean information coefficient is 0.0162, which is indistinguishable from zero.** Four names
over ten events cannot support a claim about whether low-volatility predicts returns, and this
showcase does not make one. What is demonstrated is that the measurement runs on a published
artifact and is checked by an independent oracle — not that the alpha works.

Both members with an eleven-close lookback publish 11 events; reversal, needing six, publishes
16. The members' schedule is not trimmed to fit the signal: sessions without enough history decline,
and that is asserted rather than hidden. The ensemble's horizon opens on the first day all three
members have a weight on record, because a decision that reads an empty window is what
`vqapr check` refuses (`check.lookback.uncovered`) and, since record 168, what `freeze`
refuses as well.

## What is checked, and what each check would catch

Every gate below was verified by mutation — a deliberate defect in the code it covers must make the
showcase exit non-zero. Four of the first six mutations **survived** the initial version and the
gates were rewritten until all six were killed.

| Assertion | Killed mutation |
|---|---|
| all three members published and subscribed | — |
| `member_count == 3` on every netting row | member count misreported |
| gross weight per event == 3 × 2 × budget, within a quantum-derived tolerance | netting silently drops a member |
| `net == long + short`, `offset == min(long, |short|)` per row | netting arithmetic |
| some ticker-event has members on both sides | the family never actually split |
| low-vol shorts are all at least as volatile as its longs | the sign flipped — high vol preferred |
| IC recomputed by an independent exact-rational oracle | IC replaced by a constant |
| forward return is strictly the next session | lookahead in the measurement |
| fill-journal replay == committed Account | execution accounting |

## Three things the first version got wrong

Recorded because each was a real defect in this showcase, caught by its own mutation battery rather
than by review.

1. **The original rolling helper was decorative.** The member consumed only the last result after
   computing and discarding every earlier rolling step. The direct trailing slice produces the
   same statistic with less code and work.

2. **The orientation oracle had a lookahead.** It compared published weights against volatility
   computed from closes up to *and including* the session — a close the member could not have seen
   at its 08:30 callback. The member was correct; the checker was not.

3. **The orientation oracle then demanded an ordering the construction cannot express.**
   `equal_weight` sizes by the *sign* of the demeaned signal and discards magnitude, so the
   published panel carries two distinct weights, not four. The claim that actually holds is a sign
   partition: every name held short is at least as volatile as every name held long.

## Where the alphas live, and why

None of the three alphas is in `src/vqapr/`. PRD §2.7 says vqapr may ship reference components but
does not lock project-owned proprietary alpha into package built-ins, and the module map gives
StrategyModel built-ins as **없음** for that reason. All three members are project-local component
files written by the run, exactly as show_006 does it.

What the package supplies is the non-trivial portfolio and analysis surface: `equal_weight`,
`rescale`, `net_members`, and `information_coefficient`. Nothing in `src/vqapr/` learns what a
low-volatility alpha is.

`outputs/` is gitignored, and each replicate builds its own project under it.
