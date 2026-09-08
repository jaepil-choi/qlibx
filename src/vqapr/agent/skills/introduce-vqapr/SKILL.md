---
name: introduce-vqapr
description: Explains what vqapr is, initializes a workspace, and walks a complete sample backtest end to end. Use when the user is new to vqapr, asks what it can do or where to start, wants to install or initialize it in a project, or needs routing to the right vqapr skill for registering data, authoring a component, running a backtest, or reading results.
---

# vqapr — what it is and where to start

## What vqapr is

A deterministic backtesting framework for quantitative portfolio strategies. It takes registered
datasets and strategy components, materializes evaluation data, runs simulations against a
declared venue, and produces measurement results. **It validates every input before executing** and
refuses with structured diagnostics when something is wrong.

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Before authoring anything, see one run happen

```bash
vqapr new sample --out ./first-run
vqapr register ./first-run/sample.yaml
vqapr check sample-run
vqapr run sample-run
vqapr show run sample-run
```

That writes a complete journey the product runs as it stands: a five-day reversal strategy, a
venue, a small synthetic panel, and `sample.yaml` — the one declaration that registers all of it.

The panel is **deliberately unbalanced** — one name lists late, one stops trading early — so what
you see is the shape a real run has. It is synthetic: ten names over three years of real KRX
sessions, with prices and names made up. **Draw no conclusion about a market from it**; do copy its
`sample.yaml` when writing your own declaration.

[references/sample-journey.md](references/sample-journey.md) walks what each step produced and what
to look at.

## The shape of the work

Three rungs, each depending on the one before:

1. **Registration** — every dataset, source, component and execution input registered and passing
   validation.
2. **Run** — a completed run producing a result per model: a record and tables per strategy, or a
   registered dataset per datamodel.
3. **Measurement** — the values a report needs, read back from what the run froze.

And four things the user writes, which is the whole extension surface:

| you write | it decides |
|---|---|
| **DataModel** | what a value is |
| **StrategyModel** | how capital is divided |
| **Exchange** | where and by what rules an order fills |
| **Constraint** | what must be respected |

[references/mental-model.md](references/mental-model.md) has what vqapr owns versus what the
project owns, which is the question behind most "can vqapr do X".

## Which skill to use

This skill is orientation. The work happens in eight others:

| the user wants to | skill |
|---|---|
| load their own price / fundamental / signal files | **register-dataset** |
| compute a reusable derived panel — a beta, a factor, an ML prediction | **make-datamodel** |
| write the alpha: signals into weights | **make-strategy** |
| decide when an order fills, at what price and cost | **make-exchange** |
| cap, limit or restrict the book | **make-constraint** |
| declare, check and execute a run | **run-backtest** |
| get returns, costs, tables and paper figures out | **analyze-result** |
| see what is registered, what a run used, what to delete | **inspect-workspace** |

Each is self-contained. Do not read this file for the details of any of them.

## Installing the skills into a project

```bash
vqapr skill install                # both targets
vqapr skill install --dry-run      # what it would write, and each file's state
vqapr skill list                   # what is installed and whether it matches this package
```

Both targets receive **identical bytes**. `skill list` reports, per skill and per file, whether it
is `current`, `outdated` (an earlier release's copy — updated silently) or `modified` (differs from
every release vqapr has shipped, so it holds edits that are not ours to discard; `--force`
overwrites). A file at a path vqapr never shipped is reported and left alone.

[references/install-and-environment.md](references/install-and-environment.md).

## Reading what a command returns

Every command returns exactly one line of JSON to stdout, and success and failure share a shape so
there is one parsing path. **When `ok` is false, read `fix` first.**

There is no per-status recovery catalogue anywhere in these skills, and that is deliberate: the
refusal carries `status` (who must act), `stage` (where it closed) and `cause` (what happened),
plus `fix`, `requirement`, `observed` and `source`. Prose restating those goes stale every release.

[references/reading-the-envelope.md](references/reading-the-envelope.md) explains the fields and
the order to branch on them.

## What this skill will not do

- bypass package validation
- guess missing semantics
- confirm a binding before the evidence exists

Those are the same three the other eight hold to. Where a choice changes the economic meaning of a
result, the user makes it.

## CLI reference

`vqapr --help` for the verb list, `vqapr <command> --help` for one command's arguments. **The CLI
help is the authoritative usage reference** and these skills do not duplicate it.

## Friction logging

When something is harder than it should be, write it down **before** resolving it:

- what you were doing
- what you expected
- what actually happened
- how long it took, and how you resolved it
- what would have prevented it

This log is a deliverable. The framework improves from honest friction, not from workarounds.

---

A refusal carries its own status, stage and cause. Status **423 or 503 means wait and retry the
same command unchanged**; **500 or 502 is a vqapr defect**: do not work around it, report it with
the envelope.
