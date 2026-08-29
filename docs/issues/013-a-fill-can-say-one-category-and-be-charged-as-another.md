# 013 — A fill can say one category and be charged as another

**Status:** open. Found 2026-08-28 by the red-team lane of the Slice B completion gate, while
attacking `vqapr new exchange --profile krx`. Demonstrated with a real run, not reasoned about.
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

Not a repair to specify blind. The open question is **which statement wins**, and there are three
defensible answers:

1. **The roster wins, and the venue stops declaring categories.** Consistent with the direction of
   `docs/issues/008` — identity moved to the project, and venues lost their `instruments`
   parameter for that reason. But `krx_rules` needs a category to build terms at construction
   time, before any roster is bound, so this requires the terms to be resolved later than they
   are now.
2. **The venue wins for cost and the roster for identity, stated as such.** Cheapest, and it makes
   the split explicit rather than accidental — but it leaves `kind` and the charge disagreeing by
   design, which is the thing that reads as a defect.
3. **They must agree, and a disagreement is refused.** A new judgment at `check`, comparing the
   registered roster against every registered venue's declared categories. Catches it before a run
   is spent, and costs the ninth code.

The measurement that argues for doing something: `ExchangeRulesView.charge` is a lookup in the
construction-time `listings` mapping and never reads `self.registry`, while `stamped_kind` reads
only the registry. The two paths are deliberately separate — that separation is documented and
correct for what each is for — and nothing joins them.

## Reproduction

Scaffold a KRX venue with `--profile krx`, set one instrument's `UNIVERSE` entry to a category the
registered roster does not agree with, register both, and run. The run completes `ok:true`; compare
`vqapr.fill`'s `kind` column against the `tax` charged on a sale of that instrument.
