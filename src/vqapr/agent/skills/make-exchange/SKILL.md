---
name: make-exchange
description: Writes and validates a vqapr Exchange — the venue that decides when an order fills, at what price, in what quantity increments, and at what cost. Use when the user asks about execution, fills, slippage, commissions, transaction tax, lot sizes, price limits, or trading at the open versus the close, or wants to switch between a frictionless academic backtest and a realistic one.
---

# Write a vqapr Exchange

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Start from the scaffold

```bash
vqapr new exchange <id> --instruments A005930 A000660 --out venue.py
vqapr new exchange <id> --profile krx --instruments ...
```

writes a runnable Exchange plus the declaration that registers it. `--profile krx` builds the
listings from `krx_rules`, which is the one call that gets the ETF sale-tax exemption right — a
share pays it and an ETF does not. Do not hand-write those rates.

**Every instrument the run trades needs a listing here**, or preflight refuses it by name.

`AcademicExchange` and `KrxExchange` are the only two profiles a registered Exchange may be. The
default `--profile academic` fills free, **which is what makes it academic**.

## Two traps, before you write anything

**1. `--profile krx` is long-only, and the venue has to agree with the account.**

`krx_listings` sets `access=ListingAccess.LONG_ONLY` on every rule it builds. Pairing it with
`initial_account.mode: SIGNED` is a combination **nothing refuses at scaffold time** and that
cannot hold a position — the account permits the short and the venue declines it, every time.

**2. There is no shipped costed signed profile.**

A costed long/short book needs a venue you write. Set `access=ListingAccess.SIGNED` on your own
listings — that is the member for a rule that may be held either way — and declare the costs
yourself. `--profile krx` is the right starting point for a long-only book and the wrong one for a
signed book.

[references/access-and-account.md](references/access-and-account.md) has both, with what to check
before running.

## The venue owns its settings, and the run records them

What a venue models -- which costs, which regimes, on or off -- is the venue's **settings**: a
mapping it declares (`Exchange.settings`) whose schema is its own. `KrxExchange` takes its rates
as constructor arguments, so a registration sets them from `config:`:

```yaml
components:
  krx-taxed:
    kind: exchange
    path: venue.py
    object_name: Venue
  krx-untaxed:
    kind: exchange
    path: venue.py
    object_name: Venue
    config: {sale_tax_rate: "0"}
```

Same file, two venues, two fingerprints, two run identities: a tax-free KRX is a different
experiment and the warehouse keeps it apart. Every run records `exchange.settings` in its
`strategy.json` (`vqapr show strategy`), including `not_modelled` -- what the profile does not do
-- so a reader learns what a past run measured under from the record, never from the source.

Rates are decimal **strings** in config (`"0.002"`), never floats.

## What a venue is handed

`ExecutionCall`: the order batch, the market state at that instant (`snapshot`), the account
snapshot, and the **instrument dictionary** (`instruments`) -- what every ordered or held id is,
from the project's roster. `call.rules` is the venue's own rules bound to that dictionary. A venue
receives nothing else and stores nothing it is handed.

## Declaring cost, two ways, and the choice matters

- **A per-instrument fee** — give each listing its own `buy` / `sell` `SideCost`. Right when the
  rate genuinely belongs to the instrument.
- **A rate that follows the category** — set the class attribute `terms_by_kind`, a mapping of
  `InstrumentKind` to `TradeTerms`. The charge is then resolved per fill from the registered
  roster.

**Do not express a category-driven rate as per-instrument costs.** That keeps a second copy of
what the roster already declares, and the two can disagree — the fill records the roster's category
while the money follows yours. Nothing detects it, because per-instrument rates are legitimate when
they are not standing in for a category.

[references/cost-model.md](references/cost-model.md).

## What the venue decides, and what it does not

A venue declares fill timing, tradability, direction, per-instrument quantity granularity and cost
capability. It does **not** decide whether a negative position is allowed — that is the account's
state-transition validity, frozen at the start of the run.

Keeping those separate is deliberate. Merging them produces the false pairing "academic, therefore
fractional", and makes it impossible to treat the same instrument differently at two venues.

[references/execution-profiles.md](references/execution-profiles.md).

## When the fill happens, and at what price

The price used for a fill is an **explicit declaration**. vqapr does not choose one and does not
fall back to another when the declared one is missing or invalid — it fails.

**vqapr knows the fill time; it does not know when the fill price was observed**, because that is
not in the data. So filling at the session close using a price that was only knowable at that close
passes every check the package can make and is a look-ahead.

[references/fill-timing.md](references/fill-timing.md) — read it before choosing a fill price.

## Do not overstate realism

A label is not a claim. "KRX" does not mean the exchange is fully reproduced; only the rules
actually implemented and the limitations actually stated are claimed.

On the academic profile, cost, tax, slippage, market impact and borrow cost are **explicitly
zero** and turnover is recorded separately. Its results are `hypothetical` and must not be
described as broker-confirmed, or as evidence of borrow, collateral, margin or a real short
capability.

## Validate before you believe it

```bash
vqapr register <declaration.yaml>
vqapr check <run-id>
```

A venue that imports and loads is not thereby compatible. The package judges deterministically
whether its fill table, quantity rules and cost rules keep the order-conversion invariants, and
**a local Exchange cannot redefine account authority, valuation or the run lifecycle.**

If a declaration has drifted far from the contract, generate a fresh one with `vqapr new` and move
your rules in.

## Stop condition

`vqapr check <run-id>` returns `ok: true`, every traded instrument has a listing, the venue's
`access` and the account's mode agree, and the user has confirmed which observation is the fill
price and that it was knowable at the fill time.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 or 502 is a vqapr defect**: do not
work around it, report it with the envelope.
