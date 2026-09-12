# 153 — a judgment that could not look is not a judgment that passed

**Closes:** `docs/issues/archive/077`. **Branch:** `step-02b-077-blocked-is-not-passed`, off `develop @
87ffe2c7`. **Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 2b.
**Authority:** the owner, 2026-09-04 (decision D7).

## Why this exists

`judgments()` already had the right mechanism, and its own comment said why better than the issue
could: a judgment that fails to answer "did not find nothing, it could not look, and a run nothing
was proven about would then report as clean and ready. So it is recorded as BLOCKED." Each judge
runs inside a wrapper that turns an exception into a blocked entry, and `check` marks the phase
unpassed while anything is blocked.

Five helpers caught **inside** that wrapper and returned an empty result. An empty result is
indistinguishable from "asked the question, found nothing wrong", so the mechanism never fired.
Two reproductions, from unrelated causes, both produced:

```
{"ok": false, "passed": ["workspace", "run", "judgments"], "blocked": [],
 "codes": ["source.scan.distinct.unreadable"]}
```

`judgments` in `passed`, `blocked` empty — while AC-C5, the look-ahead judgment `015` exists for,
never ran. The run was still refused, but only because preflight happens to reach the same doors,
and no test pinned that coupling. `check`'s stated purpose is letting a reader tell "this passed"
from "this never ran" from "this failed", and that is precisely what broke.

Found by a full audit of every exception handler under `src/vqapr` — 143 handlers plus 10
`contextlib.suppress` — run at the owner's request after `076`. The rest of the sweep was clean;
the three smaller sites it turned up are recorded in the issue rather than fixed here.

## What changed

All in `src/vqapr/flow/judgments.py`.

- **`_decide_agenda` → `_agenda_once`.** The agenda is now reached through a **call**, not handed
  over as a value. It is still derived at most once (`069`), but the failure is stored and
  re-raised to every asker instead of being flattened to `None`, so it lands inside the per-judge
  wrapper. Both judgments that share the agenda block, carrying the same reason — blocking one and
  passing the other would be a report that contradicts itself.
- **`_judge_datasets_and_fields` → `_members` + `_judge_member_datasets`,** and `judgments()`
  dispatches **one judge per member**, named `datasets[<component-id>]`. The old loop `continue`d
  past a member whose component would not load, reporting the whole judgment as passed. Blocking
  the whole judgment instead would be the opposite error — this verb promises every INDEPENDENT
  problem at once, and one member failing to load says nothing about another member's datasets.
- **`_judge_execution_ordering`** no longer swallows a `VqaprError` from `workspace
  .execution_input(...)`, and no longer reads `agenda is None` as "nothing to report".
- **`_judge_weights`** no longer swallows a failure to load the exchange.
- **`_instant`** returns `None` only for a value that is genuinely absent. A value that is present
  but is not an aware instant now raises. Returning `None` for it read, at the call site, as
  "nothing was declared", so a dataset whose span could not be parsed left the lookback question
  silently unasked.
- **`_first_decision`** takes the agenda call. Its `None` now means only "the run declared no
  horizon" — the period judgment's business — rather than also meaning "the agenda is
  underivable".
- The module docstring states the rule: no helper in this module catches on behalf of a judge.

`VqaprError` is no longer imported by the module, which is the shortest proof that the swallowing
is gone.

## Decisions

- **D7 (owner, 2026-09-04): the envelope carries BOTH.** When a judgment cannot answer and
  preflight refuses the same underlying defect, the report holds a blocked entry *and* preflight's
  refusal. The five `try` blocks existed to suppress the first. They are two different statements
  — one says the question could not be asked, the other says what is wrong — so both belong. The
  accepted cost is two entries for one defect.
- **The judge is named for the member, not just `datasets`.** Measured, not assumed: with all
  member judges sharing one name the blocked entry read `VqaprError: component object must load
  and construct from its registered config`, which does not say *whose*. The name is the only
  place that information exists, and nothing in `src/` or `tests/` depended on the old name.
- **Per member, not per run.** The alternative — let one bad member block the whole datasets
  judgment — is simpler and was rejected: it contradicts the verb's own docstring promise to
  report every independent problem together, and would cost the reader a round trip.
- **`test_the_lookback_judgment_stays_silent_when_it_cannot_answer` was inverted, not deleted.**
  It pinned the old behaviour on the reasoning D7 overturns. It is now
  `..._blocks_when_it_cannot_answer` and asserts both halves: the judgment blocks, and nothing is
  guessed.

## Validation

- `tests/cli/test_a_judgment_that_could_not_look_is_not_passed.py`, 7 tests: both reproductions
  (corrupt source, naive `available_at`) leave `judgments` out of `passed` with a non-empty
  `blocked`; the two agenda-dependent judgments block with the **same** reason; every blocked
  entry's `blocked_by` starts with its own `error_type`; the defect is named twice (D7, pinned so
  a later change removing either half fails loudly); an unloadable member blocks
  `datasets[my-alpha]` alone; and a healthy run still passes every judgment with `blocked == []`.
- `tests/cli/test_check.py` 18 passed after updating the five tests that reached into the removed
  helpers.
- `ruff check src/` clean; `vulture` at its two-item baseline. Full fast suite: see the merge
  commit.
