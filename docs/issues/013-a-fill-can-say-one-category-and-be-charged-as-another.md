# 013 — A fill can say one category and be charged as another

**Status: CLOSED 2026-08-29** by
`docs/implementations/079-a-venue-borrows-a-category-it-does-not-own.md` and
`docs/implementations/081-a-category-driven-rate-has-a-channel-to-go-through.md`.

`079` removed the venue's copy of the roster's categories for every venue this package ships.
`081` closed the remainder, which was the same defect available to anyone writing their own — and
not by the `check` judgment this file proposed.

**That judgment cannot work, and the reason belongs on the record.** A per-instrument rate is
legitimate when it is not standing in for a category. A venue may charge one name more than another
because of a genuine instrument-specific fee, and nothing outside can tell that apart from a
category schedule written out by hand. A judgment would have to guess the author's intent and would
be wrong whichever way it guessed. The defence is a reachable correct channel: `terms_by_kind`,
which existed for `KrxExchange` and was reachable by nobody else, is now on `rules_view` and on
`AcademicExchange` — the documented base for a user-authored venue — and `SKILL.md` states which of
the two ways to declare a cost applies when.

The original report and the superseded three-option framing follow unchanged.

---

**Superseded status (2026-08-29, partial):** closed for shipped venues by
`docs/implementations/079-a-venue-borrows-a-category-it-does-not-own.md`.

The reported defect is fixed for every shipped venue. `ExchangeRulesView.charge` resolves the
category from the registered roster through `_declared` -- the same door `stamped_kind` uses -- so
a fill can no longer say one category and be charged as another. `KrxExchange` holds no category
at all, and `vqapr new exchange --profile krx` emits ids alone. An unbound KRX venue refuses to
charge rather than assuming a share.

**What keeps this open:** nothing compares a *user-authored* venue's terms against the roster. A
venue that resolves cost from its construction-time rules can still charge on a basis the roster
does not share, and `check` has no judgment for it. That is a smaller and different problem than
the one filed -- it is now about extension authors rather than about the package's own venues -- so
the original report is kept below rather than rewritten.

---

**Status when filed:** open. Found 2026-08-28 by the red-team lane of the Slice B completion gate,
while attacking `vqapr new exchange --profile krx`. Demonstrated with a real run, not reasoned
about.
**Touches:** `src/vqapr/exchange/venues/krx.py`, `src/vqapr/exchange/listings.py`,
`src/vqapr/cli/check.py`, `src/vqapr/flow/preflight.py`.

## What happens

A KRX venue declares its own `UNIVERSE` mapping of instrument id to category, because `krx_rules`
needs the category to pick each instrument's terms. The project separately registers an instrument
roster, which is what stamps `kind` on every fill.

**They are two independent statements about the same fact, and nothing compares them.** Not
`check`, not `preflight`, not run assembly. The only thing standing between them is a sentence in
the emitted scaffold's docstring.

Observed, on a completed `ok:true` run where the venue said `etf` and the roster said `stock` for
the same instrument:

- the fill's `kind` field read `stock` — correct, from the roster
- the tax charged was `0.0` — the ETF exemption, from the venue

So the record says the run treated it as a stock, and the money says it was charged as an ETF. The
run's own `roster` envelope field reports a registered roster and a digest, which makes the two
look reconciled.

## Why it is worse than a mispriced run

`docs/implementations/067` established that `Fill.kind` is the record of what a fill was *charged
as* — it exists because the category was computed at fill time and dropped at the recorder. This
defect breaks that: `kind` now records what the **roster** said, while the charge follows what the
**venue** said. A reader auditing costs by category gets a consistent-looking table in which the
categories and the amounts come from different sources.

`cost_by_kind()` is exactly that table.

## Why it was not fixed when found

Slice B's contract is `RECORD_FIELDS` and the registration envelope. A cross-check belongs at
`check` or `preflight`, and adding one at `check` means a ninth judgment — `tests/cli/test_check.py`
pins the count at eight and its own message says *"adding a ninth is a decision, not a detail."*
That decision is not Slice B's to make.

## What the fix has to decide

## The framing this file shipped with was too generous

It first offered three defensible answers and asked which statement should win. A later question
collapsed them — *why does a venue have a universe at all?* — and the measurement that answers it
was already in this file without being followed through.

**The venue does not need a universe.** At the moment `charge` runs, the roster is already on the
same object:

- `flow/simulation.py`'s `_bind_registry_to_venue` binds the roster onto the venue itself, and says
  why in its own docstring: *"so every reader of its rules sees it"*. Handing a bound view to
  `plan_orders` alone was not enough, and a testbed journey proved it.
- `ExchangeRulesView.stamped_kind` reads `self.registry` and gets the category right.
- `ExchangeRulesView.charge` sits on that same object, in that same moment, and reads the
  construction-time `listings` mapping instead.

So the two sources are not two places the design needs; they are one place that reads from two.
`krx_rules` resolves per-kind terms **eagerly**, at construction, because `TradeRule` carries
`buy`/`sell` `SideCost` as values — and at construction no roster is bound, so the categories have
to come from the author. Resolve them lazily, from the registry the venue already holds, and the
author states the categories once, in the roster, where `008` already put them.

That makes the remaining question narrower and duller than "which statement wins": it is *where
KRX's terms get resolved*, and the answer that agrees with `008` is now known to be structurally
reachable rather than blocked by construction order.

The two alternatives are recorded because they were considered, not because they are equal:

- **The venue wins for cost, the roster for identity, stated as such.** Cheapest, and it makes the
  split explicit rather than accidental — but it leaves `kind` and the charge disagreeing by
  design, on the record `067` established as the statement of what a fill was charged as.
- **They must agree, and a disagreement is refused.** A cross-check at `check`, costing a ninth
  simulation judgment. This is a guard against a duplication that would not exist once the venue
  stops holding categories, so it is a second-best if the first is rejected, not an independent
  option.

**The scaffold propagated the duplication rather than questioning it.** `vqapr new exchange
--profile krx` emits a `UNIVERSE` mapping because that is what `krx_rules` takes, and its docstring
warns the author to keep it in step with the registered roster. A scaffold needing that warning is
the signal the shape is wrong; the warning was written and the signal was not read.

## Reproduction

Scaffold a KRX venue with `--profile krx`, set one instrument's `UNIVERSE` entry to a category the
registered roster does not agree with, register both, and run. The run completes `ok:true`; compare
`vqapr.fill`'s `kind` column against the `tax` charged on a sale of that instrument.
