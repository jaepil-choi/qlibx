# 020 — The only costed venue profile is long-only, and nothing says so where it matters

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-003**,
`slowed`, ~10 minutes *"most of it spent re-reading the skill's two cost sections looking for the
sentence that turned out not to be there."*
**Touches:** the installed skill's "Costs" and "Writing your own costed venue" sections, the
`vqapr new run-spec` template's `initial_account.mode` comment (`src/vqapr/cli/new.py:216`), and the
`--profile krx` scaffold.

## The combination the CLI lets you write and that cannot work

`vqapr new exchange <id> --profile krx` is the realistic profile, and the skill's "Costs" section
recommends it. The book here is long/short — the user asked for a Fama-French replication, so it
holds shorts. `krx_listings()` produces `LONG_ONLY` rules, so

```
--profile krx  +  initial_account.mode: SIGNED
```

is a pairing nothing refuses at scaffold time and that cannot hold a position.

## Where it *is* stated, and where a reader actually looks

The scaffold's own class docstring says it in passing, and `KrxExchange.__doc__` repeats it:

> Whole-share KRX execution: declared commission and sale tax, long positions only.

The skill's "Costs" and "Writing your own costed venue" sections — the two places a reader goes to
*decide* this — never mention direction at all. Neither does the run-spec template, which offers
`mode:` in `initial_account` with no hint that the venue has to agree. (That comment has a second,
separate defect: see **017**.)

## The mechanism, found by introspection

`ListingAccess`, which the reporter reached only through `dir(vqapr.public)`:

```
NONE       listed and quoted, never filled
LONG_ONLY  may buy, and may sell down to zero, but never below it
SIGNED     may hold a negative position; the venue claims to model the short
```

## Outcome

An `AcademicExchange` subclass with `ListingAccess.SIGNED` listings. That is also the academically
correct choice for a gross-of-cost factor replication, so the outcome is right — *"but I arrived at
it by elimination, not because anything told me."*

**Note what the correct outcome costs**, because it is the part that outlives this journey: a
long/short book cannot use the costed profile. The journey's REPORT.md records the consequence as an
assumption a reader should argue with — *"The venue is free and permits shorts. Zero cost is right
for a factor return, but this is not a tradable strategy."* Korean short-selling restrictions,
borrow availability and the 2020-21 and 2023-25 bans are all absent, and so is commission and tax.
So the question behind this file is not only where the sentence goes.

## What closes it

The docs half, which is cheap:

- The run-spec template's `mode:` comment states that the venue's listings must permit the
  direction.
- The skill's cost section states that the KRX profile is long-only, so a long/short book needs a
  `SIGNED` venue of its own, and names `ListingAccess` as the thing that decides it.

The product half, which is a decision and not obviously in scope: whether a costed **signed** KRX
profile should exist, or whether a signed book is expected to be gross-of-cost by construction. As
long as the answer is the latter, say so — the reader who wants a costed long/short book is
currently left to discover by elimination that the package has no opinion to offer them.

## Related

`docs/issues/011.1` — *"There is no reachable way to declare a per-trade cost"* — closed 2026-08-29
by making `krx_rules` reachable. This journey found the cost machinery and could not use it, for a
reason that issue did not cover.
