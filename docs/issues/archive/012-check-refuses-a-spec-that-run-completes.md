# 012 — `check` refuses a spec that `run` completes

**Status: CLOSED 2026-08-29** by
`docs/implementations/084-a-lookback-is-measured-where-something-reads.md`.

This file asked which side was wrong and refused to guess. Measured: the run's first occurrence
produced **no weight at all** — one row was visible, the strategy could not fill its declared
lookback, and it returned `Hold`. Nothing was computed on a short window, so the judgment was the
strict one.

`start` is not an instant anything reads at; it bounds the horizon, and the strategy reads at the
occurrences its agenda generates inside it. Comparing the dataset's first observation against
`start` refused every spec whose data begins after midnight. The judgment measures at the first
decision now, and still refuses a decision that genuinely lands before the data — verified with a
literal `sessions:` agenda, which is the only way to reach that case, since a `from_dataset` agenda
generates occurrences only on days the dataset has.

Noted for whoever reads this next: T5B had already made the same correction on the materialization
side (`docs/implementations/076`), which measures at the earliest `evaluate_at`. The simulation
path was left on the older comparison, and the two were written a day apart.

`SIMULATION_CODES` is unchanged at eight. This moved a reference point, not the inventory, so the
pin this issue was blocked on never had to move.

The workaround in `test_a_constraint_registered_under_the_id_it_answers_to_still_runs` is removed
with the defect it worked around.

The original report follows unchanged.

---

**Status when filed:** open. Found 2026-08-28 by the red-team lane of Slice A's completion gate,
while writing
a test that assumed `check` and `run` agree. Reproduced at HEAD `7ae3d3af` with every change from
that slice stashed, so it predates the work that found it.
**Touches:** `src/vqapr/cli/check.py` (`_judge_datasets_and_fields` and the lookback judgment),
possibly `src/vqapr/flow/preflight.py`.

## What happens

`tests/cli/test_commands.py`'s end-to-end fixture builds a workspace through the CLI alone, then
runs the spec `_spec()` emits. On that byte-identical spec:

```
$ vqapr --project-root <root> check spec.yaml
{"ok": false, "checked": [spec, workspace, judgments, declaration, preflight],
 "blocked": [], "failures": [{"code": "check.lookback.uncovered", ...}]}      exit 1

$ vqapr --project-root <root> run spec.yaml
{"ok": true, "stage": "run.complete", "occurrences": 12,
 "account_version": 2, "run_state_version": 14}                              exit 0
```

`check` says the run is not ready. `run` completes it, trades, and commits the account twice.

## Why this is the same defect as 011's constraint crash, mirrored

`docs/issues/archive/011` and `docs/implementations/068` are about `check` returning `ok:true` on a spec
`run` then refused. This is the other direction, and the approved plan's Principle 5 names both:

> **Never let `check` certify what `run` refuses — or refuse what `run` would accept.** … Both
> directions are violations, and the mirror image is arguably worse: a user cannot distinguish a
> real defect from a verb that cannot read their spec.

It is worse in a specific way. A user who trusts `check` stops here and starts editing a spec that
was already runnable. `check`'s entire value proposition is *prove it before spending a run*; a
false refusal spends the user instead.

## What is not yet known

Which side is wrong has not been established, and this issue deliberately does not guess:

- **If the judgment is right**, `run` is executing a run whose earliest occurrences cannot see the
  history the strategy declared, and the numbers it produced are computed on short windows. That
  would make the run wrong, not the judgment.
- **If the judgment is too strict**, it is refusing a legitimate spec — for instance by requiring
  the lookback to be satisfiable at the run's `start` rather than at the first occurrence that
  actually reads, or by measuring against the dataset's registered span rather than what a window
  would really return.

The first thing to do is decide that, because the two answers have opposite repairs and one of them
means a completed run reported numbers it should not have.

## Reproduction

```
uv run pytest tests/cli/test_commands.py::test_run_executes_a_declared_spec_end_to_end -q
```

passes — `run` completes. Then run `check` on the same fixture spec; it refuses. The test
`test_a_constraint_registered_under_the_id_it_answers_to_still_runs` in that file works around this
deliberately: it compares `check`'s failures with and without a constraint rather than asserting
`ok:true`, and says so in a comment, so the workaround is visible rather than silent.

## Why it was not fixed when found

Slice A's contract is the refusal set, and it may not change `check.py`'s judgments or its pinned
eight-code inventory (`tests/cli/test_check.py`), which any repair here would touch. Fixing it
inside that slice would have moved a contract the slice promised not to move.

The other red-team finding from the same lane **was** in contract and is fixed:
a whitespace-only or empty component id in a declaration reached the envelope as
`stage:"unhandled"` with a bare `ValueError` from `component_id()`. It is now a structured
`declaration.read.value_invalid` refusal naming the key and what a usable id looks like.
