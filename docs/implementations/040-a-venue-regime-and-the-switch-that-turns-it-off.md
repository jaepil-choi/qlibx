# 040 — A venue regime, and the switch that turns it off

## Why this exists

KRX limits a session's price to a base price plus or minus a declared rate. At the upper limit
there is no seller left, so a buy cannot fill; at the lower limit there is no buyer, so a sell
cannot. `TradeRule` had no field for it, and no venue could express it.

The first design put the conclusion in the registration — the user would supply *"is this name
buyable today"*. That is wrong twice over: it asks every user to reimplement a market's
regulations, and the user does not have that answer. **The user has a number** (the session base
price, already in any OHLCV panel); the venue has the rule.

The constraint that shaped everything else: a user with only close prices must still be able to
execute here. So the regime has to be switchable, and — this is the part that decides the design —
**switching it off has to be a recorded fact**, not an absence.

## What changed

**`KrxTradeRule(TradeRule)` carries the regime as a typed field:**

```python
price_limit_rate: Decimal | None = None      # None is an explicit off
def limit_band(base) -> (lower, upper)
def permits_side_at(side, price, base) -> bool
```

The rate sits on the *rule*, not the venue, because it is per-instrument in practice: KRX narrows
it for managed issues, and China runs 10% on the main boards against 20% on ChiNext and STAR. A
venue-level constant could express neither.

**`ExactExecutionRow` gained `reference`** — a second declared price, read in the *same exact
query* as the trade price. Read separately it could come from a different session and silently move
the band.

**`Exchange.execution_requirements()`** is how a venue names the execution price a regime needs,
and it is computed from what the rules actually declare:

```python
price_limits=True   ->  (ExecutionFieldRequirement("base", "price_limit"),)
price_limits=False  ->  ()
```

**Preflight refuses the third state.** Regime declared, data absent, run proceeding anyway would
produce numbers that look limit-aware and are not:

```text
preflight.execution.requirement_missing
  observed: price_limit needs price 'base'
  retry: register the required execution price, or construct the Exchange with that
         feature disabled, then retry
```

The message names **the feature to switch off**, not only the missing column, because both are
valid fixes and only the user knows which they want.

**A blocked order is typed zero-dealt, not a batch failure.** Limit-up is a market fact for one
session, so the rest of the rebalance still executes — the same reasoning as record 020 for
delistings.

## Why a typed subclass, settled

This was the open design question from the previous session, and the toggle requirement answers it.
A free-form `extras` dict cannot distinguish three states that must be distinguished:

| | misspelled key | switched off | never had the regime |
|---|---|---|---|
| `extras` dict | `KeyError` mid-run, or silently inert | absent | absent — **same as off** |
| typed subclass | `TypeError` at construction | `= None`, in the fingerprint | different type, in the fingerprint |

Record 039 made `declaration_identity` collect subclass fields automatically, so all three are now
distinct declarations. A run record can state which one it measured, which is the whole reason the
switch is safe to offer.

## Trade-offs

**A regime with no reference price is inert rather than refused, inside the venue.** `execute`
cannot know whether the user chose to omit the base price or forgot; preflight can, and does. The
venue therefore does not guess a base price, and the pairing is caught before the run rather than
during it. If someone constructs a venue by hand and skips preflight, the regime is silently off —
that is the cost of keeping `execute` free of registration knowledge.

**One reference price per venue.** `SimulationFlow` refuses a venue declaring more than one. A
regime needing two references (a band table keyed by yesterday's close *and* a reference volume)
would need this widened. Nothing needs it yet.

**`slots=True` breaks zero-argument `super()`.** A slotted dataclass subclass must call
`TradeRule.__post_init__(self)` explicitly, which is noted at the call site so the next subclass
does not rediscover it.

## Validation

- `uv run pytest -q` — **638 passed**; `uv run ruff check src tests` clean.
- **All three guards discriminate.** Disabling the fill-time check fails 2 tests; removing the
  preflight check fails 1; declaring the requirement unconditionally (ignoring the switch) fails 2.
  Restored, 15/15 pass.
- The regime is measured, not asserted: band `(7000, 13000)` from base `10000` at 30%; a buy at
  `13000` is `NONTRADABLE` with the requested size still visible, while a **sale** at the same
  price fills — limit-up blocks buying, not selling.
- The switch is proved end to end: with limits off the same order at the same price fills, the
  venue requires no extra price, and preflight freezes a run whose table carries only a trade price.
- `tests/test_workspace_concurrency.py` flaked once on a Windows file lock and passes 3/3 on rerun;
  unrelated.
