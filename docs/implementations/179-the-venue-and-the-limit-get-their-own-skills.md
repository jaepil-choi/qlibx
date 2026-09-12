# 179 — The venue and the limit get their own skills, and both lead with a combination nothing refuses

**Closes:** PRD §11.2 (two more of the nine), §6.3–6.5, §7, §12.3. **Branch:** `develop`, on top of
record `178`.

## Why

These are the last two of PRD §12.3's four extension points, and before this they had no
documentation at all — about forty lines inside a section on registration, and CLI help.

That is a poor place for them, because both carry a failure that **nothing refuses at write time**.
A skill that is reached when the user says "I want realistic costs" or "cap each name at 5%" can
lead with the trap; a paragraph buried in a registration walkthrough cannot.

## What was built

**`make-exchange/`** — SKILL.md (124 lines) and four references: `access-and-account.md`,
`execution-profiles.md`, `cost-model.md`, `fill-timing.md`.

**`make-constraint/`** — SKILL.md (129 lines) and three: `project-and-monitor.md`, `tolerance.md`,
`declaring-data.md`.

## The two combinations nothing refuses

**`--profile krx` with `initial_account.mode: SIGNED`.** `krx_listings` sets
`access=ListingAccess.LONG_ONLY` on every rule it builds. Paired with a signed account it
scaffolds cleanly, registers cleanly, and **cannot hold a position** — the account permits the
short and the venue declines it, every time. Neither half is wrong alone, so nothing catches the
pair. The skill puts it above the API, with the table for resolving it, and adds the consequence:
**there is no shipped costed signed profile**, so a costed long/short book is a venue the user
writes.

**A category rate written as per-instrument costs.** The fill records the roster's category while
the money follows the venue's per-instrument rate, and the two can disagree. Nothing detects it,
because per-instrument rates are legitimate whenever they are not standing in for a category — so
the guard has to be the author's, which makes it a thing to say rather than a thing to check.

## The distinction `make-constraint` exists to teach

One declaration goes to two consumers asking **different questions**, not the before and after of
one:

- `project` — *what is the best portfolio inside this limit?* Best effort, at decision time,
  returning **the box** (every instrument's lower and upper bound) rather than the offenders or a
  correction.
- `monitor` — *did what I actually hold exceed it?* An observation of fact on the committed state,
  after the fills, on its own cadence.

And the rule that follows: **construction is not separately scored for effort.** Scoring the same
decision twice risks two verdicts that disagree, with no way to say which is the fact about that
strategy.

`tolerance.md` states the other half — write the strict comparison and let the framework judge the
excess in one place, because per-constraint epsilons would make the three counts un-addable and
would hide the ruler inside a user's method.

## Two smaller things worth recording

**An empty `vqapr.monitoring` table means never evaluated, not never breached.** A constraint that
failed to get its data and one that held perfectly are silent in exactly the same way. Both skills'
stop conditions say to check.

**A periodic constant belongs in a DataModel, not frozen into a constraint's source.** The value has
an `available_at` and a constant in source has none; and editing the file to change the number
re-registers the component under a new fingerprint, which reads as a different rule rather than the
same rule with a new input.

## Trade-offs

**`fill-timing.md` states the same-close rule as settled and closed.** Deciding at the close on
close data and filling there is forward-looking; the reference says so and says not to implement it
or offer it. That is stronger than the surrounding prose, and deliberately — it was ruled on once
and re-litigating it costs more than the rule does.

**The warning about an unobservable fill price stays a limitation, not a validation.** vqapr knows
the fill time and not when the price was observed, so the pairing passes every check it can make.
Widening the package's judgment here would create a guarantee that is only half true, and a half
guarantee invites more trust than none.

## Validation

- `uv run pytest tests/ -q` — 1,563 passed, 25 deselected, 1 xfailed. The two `tests/extension/`
  failures are a parallel session's `43f59eb0` and predate this work.
- `uv run pytest tests/cli tests/characterization -q` — 346 passed.
- `tests/agent/` — 95 passed, 1 xfailed. Record `177`'s structural contract covered both new skills
  unchanged, for the second time.

Seven of the nine now exist. `inspect-workspace` and the reduction of `introduce-vqapr` to what is
left after the cuts are what remain.
