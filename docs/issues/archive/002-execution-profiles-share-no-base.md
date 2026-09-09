# 002 — Execution profiles share no base, and fill ordering is unmodelled

**Status: CLOSED 2026-08-29** by
`docs/implementations/082-one-copy-of-the-contract-both-profiles-check.md` (the duplication and the
five invariants) and
`docs/implementations/083-a-venue-fills-what-the-account-can-pay-for.md` (the fill ordering).

Both halves were re-measured before being acted on, ten days after this was filed. The duplication
was still exactly as described — twenty lines byte for byte under two names, plus the eleven-line
preamble — and both lifted to functions in `execution_table.py`, not to a base class, for the
reasons this file gives. The `rules.at(target_at)` row in the "what genuinely differs" table had
gone stale: no such call exists any more.

The unmodelled half is now modelled on the venue profile: sells settle first and fund the batch, a
buy is clipped to the purse with commission inside the affordability test, and the remainder is a
partial fill with a typed `UNFUNDED` reason. The overdraw this file predicted was reproduced first
— cash 20,000, required 20,006 — and closed.

**One correction to the recommendation.** This file says the academic profile *should* keep filling
everything, as a design preference. It is narrower than that: a partial fill **cannot arise**
there. Cash exhaustion needs whole-share rounding to leave a residual and charged costs to disagree
with the plan's arithmetic, and that profile has neither. Recorded as a consequence rather than a
choice, so nobody revisits it as one.

Invariant 5 is written as the inequality this file asked for, and is now exercised rather than
merely permitted.

The original report follows unchanged.

---

**Status when filed:** open, deliberately deferred. Raised 2026-08-19 while costing a long-short
family.
**Touches:** `src/vqapr/exchange/venue.py`, `src/vqapr/exchange/venues/krx.py`

Read this before changing either execution profile.

## What is true today

`Exchange` is a `Protocol`. `AcademicExchange` and `KrxExchange` each implement it independently —
no shared base, and not even the same class shape (one is a frozen dataclass, the other a plain
class with `__init__`). Measured duplication:

| part | academic | krx | identical? |
|---|---|---|---|
| snapshot validation (`_validate_snapshot` / `_rows`) | 18 lines | 18 lines | **byte for byte** |
| `execute` preamble | 11 lines | 11 lines | **byte for byte** |
| zero-dealt dispatch skeleton | ABSENT / NO_TRADE / NONTRADABLE | same | same shape |
| order validation | 43 lines | 39 lines | partly shared |

Two copies of the snapshot contract check will drift the first time only one is edited.

## What genuinely differs, and must not be abstracted away

| axis | Academic | KRX |
|---|---|---|
| quantity | fractional | whole share; a fractional listing is refused at construction |
| costs | charged when declared (record 025) | commission plus sale tax declared by default |
| shorting | permitted | refused — `held + delta < 0` raises |
| account access | not needed | **needed**, to judge the short |
| cost effectivity | none | `rules.at(target_at)` resolves dated bands |

The short check is why the two validators have different signatures: one needs the account, the
other does not. That is a real asymmetry, not an accident of style.

## The part that is not modelled at all — the actual revisit

**Both profiles fill every order independently, in one pass, at the selected price.** There is no
sequencing and no budget feedback between fills. That is fine for the academic profile, which
claims nothing else. For a venue profile it is a missing rule, not a simplification:

- **Sells should settle before buys.** Proceeds from a sale fund the purchases in the same batch.
  Filling in instrument order instead means a batch can be judged unaffordable that a real desk
  would have executed comfortably.
- **Costs consume cash that the plan already allocated.** `plan_orders` sizes against NAV; the
  commission and tax are charged at the fill. A batch that exactly spends its cash therefore ends
  slightly overdrawn once charged, and nothing currently notices.
- **A short buy would need partial fills.** When the money runs out mid-batch the honest result is
  fill-what-you-can and report the remainder as a typed shortfall, not all-or-nothing. `Fill`
  already carries `requested_quantity` separately from `dealt_quantity`, so the shape exists; no
  profile produces a partial.

`krx.py` currently lists "partial fills from liquidity or participation limits" under *not
implemented, and therefore not claimed*, which is honest. Partial fills from **cash exhaustion**
are a different cause and are not on that list either way.

## Recommended shape when this is picked up

1. **Lift the duplication to functions, not to a base class.** The snapshot check is a contract
   check, not a venue policy — it belongs beside `ExactExecutionSnapshot` in
   `execution_table.py`. Same for the `execute` preamble.
2. **Leave `execute` on each profile.** `load_exchange` refuses a subclass whose `execute` is not
   its profile's (`type(exchange).execute is not profile.execute`). A shared `execute` on a base
   would blur which profile's semantics a subclass is claiming, and that check is what lets
   `CostedExchange` add a cost band without asserting a realism it has not shown.
3. **Add sequencing to the venue profile only.** Sells, then buys, with cash carried across the
   batch and a partial fill when it runs out. The academic profile should keep filling
   everything: its whole purpose is to isolate signal from friction.

## Invariants worth pinning as tests either way

These hold for any profile and are already implied by Architecture 6.1:

1. one fill per request, in `instrument_id` order
2. absent row → `ABSENT`; `is_tradable=false` → `NONTRADABLE`; `delta == 0` → `NO_TRADE`
3. `is_tradable ⟹ price > 0`, else batch failure
4. `orders.account_version == account.version`
5. `dealt_quantity` shares the sign of `delta_quantity`, and `|dealt| <= |requested|`

Point 5's inequality is currently always an equality. Writing it as an inequality is what makes
room for partial fills without changing the contract later.
