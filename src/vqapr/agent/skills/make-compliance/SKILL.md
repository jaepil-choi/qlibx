---
name: make-compliance
description: Writes and validates a vqapr Compliance rule — a position limit, sector cap, exposure or mandate rule observed on the committed book at every instant of the market clock — and shows how a strategy bounds its own portfolio with the shipped kit (`no_short`, `single_name_cap`, `intersect`). Use when the user wants to cap, limit, or restrict a portfolio; mentions a mandate, guideline, risk limit, or compliance rule; or asks why a rule reported a breach instead of changing the portfolio.
---

# Write a vqapr Compliance rule

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Two things, and they are not two halves of one

```
the box      the strategy builds inside a limit    decision time    best effort — the strategy's
the rule     did the book actually exceed a limit  market clock     observation of fact — the framework's
```

**A constraint is not an extension point.** The box a strategy builds inside is the strategy's
discretion, so it is a kit call inside `decide()`, not a component the framework runs:

```python
from vqapr.public import intersect, no_short, optimize, single_name_cap

names = tuple(sorted(call.window.instruments))
lower, upper = intersect(no_short(names), single_name_cap(names, benchmark, Decimal("0.10")))
result = optimize(desired=desired, current={}, lower=lower, upper=upper, cash_range=(Decimal("0"), Decimal("1")))
return Rebalance(target_weights=result.weights, cash_weight=result.cash, budget=BUDGET)
```

Every function is pure: names and numbers in, a `(lower, upper)` box out. A rule that needs data
— `single_name_cap` needs the index weight per name — is handed it by the strategy, which
**subscribes to that dataset itself**, so the dependency is visible on the strategy where it
belongs. [references/the-box.md](references/the-box.md).

**Compliance is the extension point.** A `Compliance` rule observes the committed, marked book at
every instant of the market clock, right after valuation, and leaves a finding. It does not shape
the portfolio and it does not stop the run.

## Compliance rules are optional

Not a precondition for research. Only a workflow that wants actual-account monitoring has to
supply a metric, a bound and the data behind them.

A run names its rules in a `compliance:` list **on the run**, beside `exchange:`, pointing at
registered components of kind `compliance`. On the run and not under the strategy, because a
rule's parameters are its own.

## Start from the scaffold

```bash
vqapr new compliance <id> --cap 0.2
```

writes a single-name position cap that registers and runs unedited.

## One member: `observe`

```python
class Cap(vq.Compliance):
    @property
    def compliance_id(self) -> str: ...          # equals the id it is registered under
    def inputs(self): ...                        # what it reads, as of the instant observed
    def observe(self, call) -> vq.ComplianceFinding: ...
```

`observe` receives one `call`, and everything the rule may reach is on it — the marked account
as `call.account` (cash, positions, marked values, NAV, `call.account.weights()`) and the rule's
own reads — and returns a `ComplianceFinding`: `passed`, `measured`, `bound`,
`excess`, `offenders`. A rule keeps `memory` between observations, so *"out after three
breaches"* can count. [references/observe.md](references/observe.md).

## The rule's parameters are its own

A rule is **not** handed the box the strategy built inside, and it does not inherit the
strategy's targets. A watcher that inherits the target of the thing it watches is grading itself.
The strategy's cap and the rule's cap are two declarations of one number; when they differ, that
is information, and the report shows both.

## Compare strictly; the framework applies the tolerance

A book executes in whole lots and is marked after its fills, so a realised weight lands a little
off the target. **Write the strict comparison** and let the framework judge the excess against
`max(bound × 1%, 10bp of NAV)` — once, in one place — and file it as `held`, `within_tolerance` or
`breached`.

Only `breached` makes the contract `ok: false`, and all three counts are reported so nothing is
hidden.

Override the line with a `tolerance` property returning a `Decimal` share of NAV. `None`, the
default, keeps the framework's. [references/tolerance.md](references/tolerance.md).

## A rule declares the data it needs

And **fails before producing a finding** if that data is absent. A missing input is never read as
"within limits". [references/declaring-data.md](references/declaring-data.md) also covers where
a periodic constant belongs — a fixed value for a period is published by a DataModel and
subscribed to here, not frozen into the rule's source.

## A breach never stops a run

It is recorded. `vqapr show strategy` reports it under `contract`, and `vqapr.monitoring` holds one
row per rule per market-clock instant: which rule, what the bound was, what was measured, and who
offended.

That triple — **which rule, what was the limit, what was it actually** — is deliberately all that a
violation record requires. Demanding more makes observation heavy, and heavy observation cannot run
often, so it ends up running less.

## Two built-ins, on both sides

`no_short` and `single_name_cap` exist twice, on purpose: as kit functions the strategy builds
inside, and as shipped rules (`vqapr.public.shipped_compliance_path("no_short")`,
`("single_name_cap")`) that observe the book against their **own** copy of the number.

The rule `single_name_cap` subscribes to **time-varying point-in-time** benchmark constituent
weights. A name **confirmed** to be outside the benchmark has `w_i^index(t) = 0` — but if the
membership or the weight data is **missing**, the observation fails rather than assuming zero.

Sector, turnover, liquidity, leverage and gross/net exposure rules are not shipped. Writing one
yourself is not blocked, as long as it fits the contract above: declare the data, observe the book,
measure the value.

## Validate before you believe it

```bash
vqapr register compliance <id> <file.py>
vqapr check <run-id>
```

A component that imports and loads is not thereby compatible. If a declaration has drifted far
from the contract, generate a fresh one with `vqapr new` and move your rule in.

## Stop condition

`vqapr check <run-id>` returns `ok: true`, and after a run `vqapr.monitoring` holds rows for this
rule — an empty table means it was never evaluated, which is not the same as never breached.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 is a vqapr defect**: do not work
around it, report it with the envelope. **502 is your own code raising** — `cause.origin` is
`"user"` and `cause.where` is your file and line; fix the component. **503 is the machine** — retry
unchanged.
