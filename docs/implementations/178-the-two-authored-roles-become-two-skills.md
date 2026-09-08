# 178 — The two authored roles become two skills, and each one leads with its own trap

**Closes:** PRD §11.2 (two more of the nine), §2.3, §5.4–5.7. **Branch:** `develop`, on top of
record `177`.

## Why

`make-strategy` and `make-datamodel` are the two halves of PRD §2.3, and the old body treated them
unevenly: about eighty lines on writing a strategy, and the DataModel explained in passing inside a
section about registration — its output typing, its lookback choice and the fact that it is a run
scattered across three places that were mostly about something else.

That imbalance is the defect. Of the four extension points PRD §12.3 gives the user, only
StrategyModel was documented; the other three were left to CLI help.

## What was built

**`make-strategy/`** — SKILL.md (152 lines) and five references: `reading-inputs.md`,
`memory-and-payload.md`, `rebalance.md`, `composition-and-budget.md`, `public-helpers.md`.

**`make-datamodel/`** — SKILL.md (126 lines) and four: `datamodel-or-strategy.md`,
`reading-inputs.md`, `output-schema.md`, `running-a-datamodel.md`.

Each SKILL.md leads with the decision that is hardest to reverse rather than with the API.

## The traps each one leads with

**`Rebalance.of` cannot say "more shorts than longs".** It splits `invested` evenly between the
sides, so it tops out at half a textbook long/short book. A strategy whose signal decides the split
and which uses `of` produces a book that runs, reports and is not the one the signal asked for.
`rebalance.md` puts the two constructors side by side with a table for choosing, because the
failure is silent.

**`save_payload` must be deterministic and `load_payload` must accept empty bytes.** Preflight
proves the pair by saving, loading into a second fresh instance, and saving again — the two byte
strings must match. So a timestamp, an `id()` or unordered set iteration fails step three, and the
default `save_payload` writing nothing means a bare `pickle.load(source)` refuses the run with
`EOFError` before any decision. Both are in `memory-and-payload.md` with the fix, because the
refusal names the step but the reader still has to know why the step exists.

**The lookback pair.** `RowsLookback` gives each name its own last N observations, so on an
unbalanced panel a 313-row request spanned 1,865 sessions and eight years; `CalendarLookback`
gives every name the same window. A correlation matrix built on the first mixes a live name's
recent returns with a delisted name's decade-old ones, and **every number is finite and every check
passes**. Both skills carry this, from their own angle — a strategy asks what `decide()` is handed,
a DataModel asks what a cross-sectional calculation needs — rather than one linking to the other.

**A DataModel's output schema is written by its first non-empty session.** Nothing is cast
afterwards, so a model returning `int` on a quiet session and `float` later passes session one and
is refused on session two. `output-schema.md` says to decide the type in the code rather than let
the data decide it.

**The DataModel / StrategyModel test is execution, not account access.** An allocation can be
filled and a fill makes a return, so it must execute — even on the zero-friction profile, where the
cost is zero but the fill, the account and the feedback are real. A value has nothing to fill. PRD
§2.3 warns explicitly that splitting the roles by "does it see the account" gives the wrong answer,
and `datamodel-or-strategy.md` carries that warning with the worked cases either side of the line.

## What was deliberately not built

**No `examples/` directory.** The plan called for runnable example components in both skills.
`vqapr new strategy|datamodel` already emits a file that runs as written, generated from the
contracts the package enforces — so a hand-written example is a second copy that can drift, and an
example that has drifted is worse than none, because it is read as authoritative. Both skills point
at the scaffold and say why.

This is the same reasoning that kept the dataset declaration's key list out of `register-dataset`.

## Trade-offs

**`reading-inputs.md` exists twice, once per skill, not byte-identical.** A shared file would have
to be reachable from both skill directories, which the install layout does not offer, and a
cross-skill link is the nested reference PRD §11.2 forbids. Two files written from the two callers'
angles cost less than either alternative, and the shipped-hash table keys per skill so the
duplication is expected rather than an anomaly.

**`make-strategy` says a variant "is a new file under a new id" without deciding for the user.**
There is no config channel, so whether an edit is a tuning or a new strategy is genuinely the
user's call — and it determines whether the record reads as one strategy improved or two compared.
The skill states the consequence and asks; its stop condition includes the user having agreed.

## Validation

- `uv run pytest tests/ -q` — 1,545 passed, 25 deselected, 1 xfailed. The two `tests/extension/`
  failures are a parallel session's `43f59eb0` and predate this work.
- `uv run pytest tests/cli tests/characterization -q` — 346 passed.
- `tests/agent/` — 77 passed, 1 xfailed. The structural contract from record `177` covered both new
  skills without changes: names, descriptions, body lengths, reference reachability, one-hop depth,
  forward slashes and CR-free bytes all held on the first run.
