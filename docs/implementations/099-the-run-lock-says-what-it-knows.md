# 099 — The run lock says what it knows, and names the wait that costs nothing

**Closes:** `docs/issues/archive/037-the-run-lock-heals-itself-and-no-message-says-so.md`.
**Branch:** `fix/037-run-lock-states-what-it-knows`.

## Why this change exists

A run was killed by a two-minute tool timeout, 216 of ~246 callbacks in. The identical command,
re-run seconds later, was refused:

```
"observed": "'run_ou_k0_2024' is running now at .vqapr/runs/run_ou_k0_2024 (pid 64004)",
"fix": "wait for that run to finish, or run with --run-id <new-id>. Do NOT use --force: it would
        destroy the rows that run is still writing"
```

`Get-Process -Id 64004` returned nothing. **The mechanism was right and the message was wrong**, and
the reporter's own diagnosis -- *"it never checked"* -- was wrong too. `LOCK_STALE_AFTER` is a
heartbeat threshold: a lock unrefreshed for 120 seconds reads as abandoned and the dead run's id
frees itself. What actually happened is that the kill and the retry were seconds apart, inside the
window where a killed run and a live one are indistinguishable **by construction**. That is the
intended trade, and it is also exactly when an operator retries: Ctrl-C, a CI timeout and an OOM
kill all produce this state moments before the retry.

Three consequences reached the user as wrong information:

1. **Present-tense liveness for a state the code knows only as "recently touched"**, printing a pid
   nothing had interrogated. A reader who checks that pid concludes the package lies.
2. **The one remedy that works on a dead holder argued against, in bold**, on a premise the refusal
   cannot check.
3. **The actual remedy nowhere.** Waiting ~120 seconds clears the lock automatically. It is
   implemented, correct, safe under both readings, and appeared in no message and nowhere in
   `SKILL.md`. What the message offered instead -- *"wait for that run to finish"* -- reads as wait
   forever when the holder is dead, and is the first thing a reader tries.

## What changed

- **`_lock_holder` became `_lock_claim`, returning a `LockClaim(pid, age)`.** The age was already
  computed to make the stale decision and was thrown away; it is the one fact that tells the two
  states apart, so it is carried out with the pid. `releases_in` is derived from it.
  - **The age is clamped at zero.** A lock written microseconds ago can carry an `st_mtime`
    marginally ahead of `time.time()`; unclamped that reaches an operator as `-0s ago`. Found by the
    test below, which asserted `age >= 0` and got `-2.4e-07`.
- **`RunRecordLive` carries the claim** and its own message states a lock, its age and its automatic
  release rather than asserting a run is executing. `.holder` still exists, so existing callers and
  `tests/flow/test_run_records.py` are unaffected.
- **The CLI refusal moved into `_held_run_id`**, which is what makes the message testable without
  executing a simulation. Its three fields now say:
  - `observed` — `'run_x' holds a lock last refreshed 3s ago at <dir> (pid 64004, not interrogated)`
  - `fix` — the wait FIRST, with the seconds remaining and the fact that re-running the same command
    then reclaims the id; `--run-id <new-id>` as the immediate alternative; `--force` hedged with
    *"while the holder may be live"*.
  - `requirement` — a run id must not already be held by a lock inside its heartbeat window.
- **`SKILL.md`'s `workspace-state` section gained the run-lock paragraph** the workspace lock has
  had all along. The concept and the remedy were already written down one lock over.

## What this deliberately does not do

**No pid liveness check**, which is what the reporter proposed. A pid is not portable liveness
evidence -- it is recycled, and on Windows a foreign process id says nothing an operator can act on
-- and a check that is right on one platform and wrong on another is worse than a message that
states its own limits. The heartbeat is the evidence this design chose, and it is sound; what was
missing was saying so.

**No change to `LOCK_STALE_AFTER`.** The 120s window is argued for at length in its own docstring
and a factor run here takes three to six minutes, so the threshold is a heartbeat rather than a
duration budget.

## Validation

| check | result |
|---|---|
| `tests/cli/test_the_run_lock_refusal_states_what_it_knows.py` | 4 passed |
| `tests/flow/`, `tests/qa/` (the lock's own suites, including the concurrency races) | 199 passed |
| fast suite | **1435 passed**, 14 deselected |
| `-m slow` | **14 of 14 passed** |
| `ruff check src tests` | 14 findings, all pre-existing; none in the touched lines |

The new test builds a claim directly (`LockClaim(64004, 3.0)`) and asserts the rendered envelope
says `3s ago`, `not interrogated`, and starts its fix with `wait about 117s` — the arithmetic the
operator is owed. It also asserts the old sentences are gone, because a message test that only
checks for the new text passes while both are present.

Baseline regeneration was a pure line shift.
