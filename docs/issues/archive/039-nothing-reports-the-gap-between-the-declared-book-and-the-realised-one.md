# 039 — Nothing in a run's own reporting compares the declared allocation with the realised book

**Status:** **CLOSED 2026-08-31** by `docs/implementations/102-a-run-says-what-its-orders-did.md`
(owner-approved). `run.complete` now carries `fills` - `orders`, `dealt`, `partial`, `zero_dealt`
and a per-reason mapping - so the 3.1%-against-1.2% comparison that would have exposed this run's
real cause on day one is in the envelope rather than in 47,318 rows.

`partial` is included beyond what this file proposed, because an under-filled order is the same
declared-versus-realised gap one degree quieter, and it was 1,404 of this run's short requests.

**The realised-versus-declared exposure figure in `show run` is NOT closed here.** That is the
larger half and needs a shape decision; this closes the half where every number already existed.

*Found while wiring it:* `tables_declared` had been reading an attribute `SimulationResult` does not
have, so `docs/issues/archive/024`'s fix never reached production. Filed as `docs/issues/archive/041`.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-017**,
`slowed` / `code`. Found by accident, while checking something else.
**Touches:** the `run.complete` envelope; `vqapr show run`; `vqapr.fill`'s `reason` column;
`validate_allocation` / `AllocationInvariants` / `AllocationViolation` in `vqapr.public`.

## First, a settled data point on issue 018

`vqapr.weight` — the intended allocation per evaluation, before execution — is **exact**, at every
rebalance sampled across a full year:

```
2024-01-02  n=131  sum_long=0.5000  sum_short=-0.5000  L1=1.0000
2024-01-03  n=173  sum_long=0.5000  sum_short=-0.5000  L1=1.0000
2024-12-30  n=127  sum_long=0.5000  sum_short=-0.5000  L1=1.0000
```

So 018 — `invested` capped at 1 with `per_side = share / 2`, making textbook $1-long/$1-short
unreachable — **does not obstruct this paper.** The paper wants gross exposure 1.0, not 2.0, and
`invested="1"` on a signed book gives exactly that. That is one data point on 018's unsettled
product question, from a real paper, and it points the opposite way from the "textbook" framing.

## The finding: the realised book is not the intended one, and only `vqapr.weight` is exact

From `vqapr.account`, at rebalance instants:

```
v2    2024-01-03  long/nav=0.500  short/nav=-0.471  GROSS=0.971  NET=+0.029  n=168
v4    2024-01-05  long/nav=0.500  short/nav=-0.455  GROSS=0.955  NET=+0.045  n=148
v243  2024-12-27  long/nav=0.510  short/nav=-0.436  GROSS=0.946  NET=+0.074  n= 94
v244  2024-12-30  long/nav=0.510  short/nav=-0.419  GROSS=0.929  NET=+0.091  n=123
```

The long side lands on 0.500 essentially every time. The short side never does, misses by more as
the year goes on, and by December the book carries **+9.1% of NAV in unintended net long
exposure**. A strategy whose entire premise is neutrality to the factor structure was, by the end,
running a material directional bet.

## The cause is real, correctly modelled, and correctly labelled

`vqapr.fill` reports it:

```
reasons: [(None, 45834), ('nontradable', 1481), ('no_trade', 3)]
zero-dealt: 1484 of 47318 (3.1%)
short requests: 23868, of which under-filled: 1404
```

Names not tradable at the fill instant. Faithful market friction, asymmetric because halted and
administrative-issue names skew toward what a reversal signal wants to short. **The behaviour is
right.**

## The complaint

**The gap between declared intent and realised book is nowhere in the run's own reporting.**

`vqapr run` returned `{"ok": true, "occurrences": 732, "account_version": 244}`. `vqapr show run`
reported the period, the contract, per-table row counts and the closing account. Neither mentions
that 3.1% of fills dealt nothing, that 1,404 short requests came up short, or that gross exposure
ran 3-7% under the declared allocation all year.

The reporter's own reading of it:

> `ok: true` on this run means "the simulation executed", and I had been reading it as "the book I
> declared is the book that was held". Those differ by nine percent of NAV.

## The follow-up, which strengthens rather than weakens the case

Re-running with a screen for degenerate (frozen-price) listings — a defect in the reporter's own
model, not in vqapr — closed most of the gap:

```
                     gross    net     zero-dealt fills
before (ou-k0)       0.971  +0.045    1484 / 47318  (3.1%)
after  (ou-k0-v2)    1.006  +0.010     565 / 46325  (1.2%)
after  (ou-ff5-v2)   1.005  +0.008     618 / 38224  (1.6%)
after  (ou-pca-v3)   0.998  +0.001     111 / 36377  (0.3%)
```

So the bulk of the drift was **a symptom of a real bug in the author's model, sitting in
`vqapr.fill` the whole time, in a form no summary surfaced**. A 3.1% zero-dealt rate against a 1.2%
baseline is exactly the signal a run summary exists to raise. Had the completion envelope reported
it, the reporter says they would have investigated on day one instead of finding the cause by
accident two hours later.

## The vocabulary already exists and is already public

`vqapr.public` exports `validate_allocation`, `AllocationInvariants` (with `sign`,
`weight_sum_upper`, `tolerance`, `required_coverage`) and `AllocationViolation` — *"A typed refusal
raised before any mutation, naming the invariant and the offender."*

That is the concept, built and public. It is unmentioned in `SKILL.md` (see 021), it is not wired
into the run summary, and it appears to validate an allocation **input** rather than compare intent
to outcome after the fact.

## What would close it

One line in the completion envelope — `"fills": {"dealt": 45834, "zero_dealt": 1481, "reasons":
{"nontradable": 1481}}` — or a realised-versus-declared exposure figure in `show run`. **Every
number already exists in tables the run wrote. Nothing aggregates them.**
