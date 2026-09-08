# What vqapr owns, and what the project owns

Most "can vqapr do X" questions are really this question. The line is drawn where a difference
between two projects would make their results incomparable.

## vqapr owns

Project initialization and the frozen invocation. Dataset registration and capability binding.
Field semantics — unit, currency, timezone, universe, tradability. Point-in-time materialization
and bounded access. The contracts for signals, alpha weights, ensembles, intended portfolios and
artifacts. Order-conversion semantics and its clipping and failure diagnostics. Constraint
declaration, adjustment, validation and findings. Instrument semantics and execution-policy
resolution. Portable artifacts, lineage, catalogue and reporting. Model state and its
working/committed lifecycle. Deterministic callback delivery and the evidence a run ends with.
Actual-account monitoring. Agent-readable documentation and stage-based errors.

## The project owns

The source data **and its economic meaning**. Availability, delivery lag and restatement
assumptions. Universe, benchmark, sector and factor definitions. The signal model and the alpha
policy code. Risk, cost, constraint and execution policy. The economic meaning of a constraint
metric and its bound. Whether a compliance reference actually applies. Project-local extensions and
report composition. A strategy's decision-trigger rules and what its state payload holds. The
research objective, and the decision to promote.

## What nobody owns yet

Broker connectivity, order slicing and pacing, always-on scheduling, kill switches, confirmed
fills from a venue. Those belong to a production runtime, and **vqapr is not a broker SDK wrapper
or an always-on OMS.**

## The four extension points

| you write | it decides | shipped built-ins |
|---|---|---|
| **DataModel** | what a value is | none |
| **StrategyModel** | how capital is divided | **none** — proprietary alpha does not live in a package |
| **Exchange** | where and by what rules an order fills | academic, krx |
| **Constraint** | what must be respected | two |

**What the user cannot write**: actual account authority and its state-transition validity,
valuation and the definition of NAV, the intended → requested conversion, the run lifecycle and
event order, evidence recording. Those define what a result *means*, so a project-specific version
would make two runs incomparable.

Built-ins and project-local extensions go through **the same registration and the same
validation**. If the package let its own built-ins reach inside, a built-in would be an example
nobody could reproduce.

## The rule underneath all of it

**Anything that claims a return passes through one execution spine.** An allocation can be filled,
a fill makes a return — so it executes, even on the zero-friction academic profile where the cost
is zero but the fill, the account and the feedback are real.

A value has nothing to fill, so a DataModel's work ends before execution.

That single test is what separates the two authored roles, and it is more reliable than asking
whether something looks like data or looks like a strategy.

## Two more that surprise people

**Being findable is not being valid.** That a component's source loads proves nothing about
compatibility; registration validates the contract, and `check` proves the run.

**Explicit failure beats a silent fallback.** vqapr refuses rather than guessing a schema, a
field, or a missing semantic — including refusing to localize a naive timestamp for you, because
only the user knows which instant a value means.
