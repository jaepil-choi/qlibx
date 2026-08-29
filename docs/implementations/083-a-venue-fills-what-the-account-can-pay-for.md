# 083 — A venue fills what the account can pay for

Issue `002`'s second half, and the one it called *"a missing rule, not a simplification"*.

Both profiles filled every order independently, in one pass, at the selected price. No sequencing,
no budget carried between fills. Measured on a two-name batch where the cash covers the shares
exactly:

```
cash available : 20000
cash required  : 20006.0000
ends at        :    -6.0000
```

The venue filled what the account could not pay for, and nothing noticed. `plan_orders` sizes
against NAV; the commission is charged at the fill. A batch that exactly spends its cash therefore
ends overdrawn once charged.

## Three rules, on the venue profile only

**Sells settle before buys, and their proceeds fund the batch.** A desk funds a rotation out of the
sleeve it is rotating from. Filling in instrument order instead judges a batch unaffordable that
would have executed comfortably — the money was there, it just had not arrived yet.

**A buy is clipped to what the purse holds**, commission included in the affordability test rather
than charged after it. Solved by shrinking, not dividing: the rate applies to the notional and the
notional depends on the quantity, so `q * price * (1 + rate) <= purse` gives the bound directly and
the listing's quantity step rounds it down to something tradable.

**What is left when the money runs out is a partial fill.** `Fill` already carried
`requested_quantity` apart from `dealt_quantity`, so the shape existed and nothing downstream had
to learn a new one. Record `082` had just pinned that relation as an inequality for exactly this.

Same batch, after:

```
cash=20000  required=19905.97  ends=+94.03
  AAA requested=100  dealt=100
  BBB requested=100  dealt=99   <- the first partial fill this package produces
```

## `UNFUNDED` is not a market fact

`ZeroDealtReason` gained a fourth member, and it is named apart from the other three on purpose.
`ABSENT`, `NONTRADABLE` and `NO_TRADE` are things the venue **observed**: no row, a row saying the
name could not trade, a plan asking for no change. `UNFUNDED` is something the **account** did.

Conflating them would let a reader asking *"what did the market refuse me"* count their own empty
purse in the answer.

## The academic profile is untouched, and cannot be otherwise

Issue `002` recommended sequencing "on the venue profile only", and framed it as a preference —
the academic profile's purpose is to isolate signal from friction, so it should keep filling
everything.

It is narrower than a preference. **A partial fill cannot arise there at all.** Cash exhaustion
mid-batch needs whole-share rounding to leave a residual the plan could not size away, and charged
costs to disagree with the plan's arithmetic. The academic profile has neither: its listings are
fractional, so a plan sizes exactly to the cash it has, and it charges nothing.

`test_the_academic_profile_cannot_produce_a_partial_fill` pins that as a consequence rather than a
choice — it fills a million shares against an account holding zero cash, because nothing on that
path consults a purse, because nothing on that path can leave one short.

## Settlement order does not reach the record

Fills are sorted back into instrument order before the batch is returned. Settlement order is an
execution detail; the fill table is read by run records and by comparisons that depend on a stable
order, which is invariant 1 of the five record `082` pinned.

Within each group the order is by instrument id, so a batch executes identically on every replay.
That matters here more than it usually does: the ordering decides **which** buy goes unfunded, and
a run answering differently on a rerun would make the shortfall unreproducible.

## Validation

```
uv run pytest tests/ -q -m ""    # 1347 passed, clean
uv run pytest tests/ -q          # 1333 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

The full run matters more than usual here: every showcase executes real batches through these
profiles, and `show_005_enhanced_index` is fully invested, which is the shape most likely to hit
the new clip. Nothing moved.

Four new tests in `tests/exchange/test_profile_invariants.py`, beside the five invariants: the
overdraw case with its measured before-figures, a rotation funded entirely by its own sale, the
`UNFUNDED` reason, and the academic impossibility.
