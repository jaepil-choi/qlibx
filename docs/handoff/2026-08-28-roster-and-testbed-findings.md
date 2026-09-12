# Handoff — 2026-08-28

Where this session ended, what is done, and what the next one should pick up.

Branch `jaepil-develop`, 8 commits ahead of the previous handoff point. Working tree clean except
`testbed-claude/`, which belongs to a parallel agent and is untracked deliberately.

## Verify first

```
uv run pytest tests/          # 1,298 passed, 13 deselected, ~80s
uv run pytest tests/ -m ""    # 1,311 passed, ~7min
```

**The default now deselects `slow`.** Use `test` while iterating and `test_all` before handoff —
both declared in `.agent/project.yaml`. A change to run assembly, the record shape, or the emitted
scaffolds is not verified until `test_all` passes; those thirteen tests are what cover them.

## What landed

Four issues closed, three implementation records written.

| Issue | What it was | Record |
|---|---|---|
| 007 | An undeclared instrument silently got share treatment | superseded by 008 |
| 008 | The roster belonged to the project, not the venue | 065 |
| 009 | A fingerprint should be a receipt, not a gate | 064 |
| 010 | Two writers shared one account table | 066 |

**008/009 in one line each.** The roster left the venue: venues lost the `instruments` parameter
entirely, so a venue author has no channel to declare a category, and the Flow binds the project's
roster in at run assembly. The two component-fingerprint refusals that pointed at each other are
gone — editing a registered component and re-registering now replaces it in place, and the run
record states what actually loaded.

**Both issue files contained errors that would have broken the product if executed literally**, and
both are amended in place. 009's Decision 4 named the object store as dead; it is the path
`Project.materialize` writes through. 009's Decision 2 asked whether the package version belongs in
a preimage that gates nothing; the gating preimage never carried one.

## What is open

### `docs/issues/archive/011` — the documented surface cannot reach a cost

Nine findings from two independent first-time-user journeys (`testbed/`, `testbed-claude/`), run
against the installed package with no source access. **Both journeys completed** — every gap below
is between what the package does and what its surface says it does.

The three worth doing first, in order:

1. **011.1 — no reachable way to declare a per-trade cost.** `vqapr new exchange` emits an
   `AcademicExchange` that charges nothing. `krx_rules` — which produces exactly the ETF exemption
   this session was built around, verified at `tax=2000.000` for a stock sale and `0` for an ETF —
   appears **zero times** in the installed skill and never in the scaffold. The other agent spent
   the largest block of its mission failing to find the rate and reported the question
   unanswerable. This is the capability we just built, unreachable by the documentation.

2. **011.3 — a run with no roster completes silently**, every fill `kind: None`. The proposed fix
   (have `run` state the roster it read) also closes 011.5 and gives 011.2 its missing signal, so
   it is the highest-leverage single change in the list.

3. **011.6 — constraints are advertised and undocumented.** The run-spec template offers a
   `constraints:` list; there is no scaffold, no documented signature, and five abstract methods
   including `project`, which is a semantic contract nobody can guess. A 20%-position-cap
   requirement went unmet because the agent correctly refused to guess.

The rest: 011.2 (roster unreachable and unlistable), 011.4 (`roster_id` echoed and discarded),
011.5 (partly-commented declaration drops a category), 011.7 (`KeyError: 'component'` as a
refusal), 011.8 (a `fix` naming a Python API to a CLI user), 011.9 (the templated 15:29 valuation
lags NAV by a session).

### Older, untouched

`001`–`006` predate this session and were not looked at.

## Two things worth knowing before you change this code

**The roster reaches the venue by binding, not by passing.** `execute`'s signature is fixed —
`load_exchange` refuses a subclass that overrides it — so the Flow sets `_registry` on the venue at
assembly. `AcademicExchange.rules` rebuilds its view per access and `KrxExchange` serves a cached
`_rules`, so both had to be handled; that asymmetry is why record `065`'s "partial injection cannot
happen" claim was false and `067` fixes it.

**Sizing still falls back when no roster reached the view, and that fallback has an expiry.** All
four shipped categories inherit `notional`/`quantity_for` unchanged, so today the fallback and the
declared answer are the same number. `_sizing_is_uniform()` checks this on every call and returns
False the moment any category overrides either method — the first future with a contract multiplier
turns the fallback off automatically rather than silently mis-sizing.

## Method notes, because they earned their keep

- **Both defects `067` fixed were invisible to 1,300 tests and obvious within minutes of using the
  CLI.** They lived in the gap between "the object is correct" and "the user sees it". The suite
  tested the first.
- **`--durations` hid the suite's real cost.** Its top entries were ~1.2s each, about 12s of 452s.
  Summing by file found 83% in thirteen tests. Measure by file, not by the default report.
- **I diagnosed the roster defect wrong twice before instrumenting it**, and both wrong answers
  were plausible. The plan artifacts from the ralplan run record the same pattern: seven defects
  found across review passes, the fifth inside a paragraph the previous pass had cleared.
