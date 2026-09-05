# 118 — A line count was never the thing being measured, and the ledger says what the tree says

**Closes:** the owner ruling of 2026-09-01 retiring line-count acceptance criteria, and the ledger
drift found when the Step 0–11 campaign was audited against the tree.
**Branch:** `fix/118-retire-line-count-acceptance`.

Two unrelated pieces of work, in one record because they are one instruction: *say what is true.*
One half is a gate that asserted something other than what it claimed; the other is four issue files
that disagreed with the code they describe.

## Part one — line-count acceptance criteria are retired

**The ruling: an acceptance criterion may not be a line-count cap.**

This is not a preference. The campaign produced three measurements against that shape of criterion,
and all three are failures of the criterion rather than of the work:

1. **It cost a revert.** Step 11 asked for two things at once: no `workspace/` file over 800 lines,
   **and** a pure-move diff. Record `117` measured that the pair is unsatisfiable — the `Workspace`
   class alone is 1,307 lines of method bodies, so the best four-way split left `registry.py` at
   1,403, and reaching 800 requires carving the class, which is not a move. The step shipped its
   load-bearing half and reverted the rest. **The cap did not describe a better structure; it
   described an arithmetic that could not exist.**
2. **It was unreachable and had to be amended.** Step 7's acceptance said `public.py` under 250
   lines. It came out at 328, of which **254 are imports and `__all__`** — pure surface declaration
   for the 132 names the module exists to export. Record `111` amended the acceptance. The number
   was mostly counting how many things `vqapr.public` is a surface *for*, so it got tighter every
   time the package exported something new — the opposite of what it was named for.
3. **The gate policing it was itself open.** The ceiling meant to enforce that 250 was set to 420 —
   69 lines above the real value and 170 above the target. An external review caught it (R8) and
   record `113` corrected it. A configured gate that is open is the finding record `105` opened
   this campaign with, and it recurred inside the campaign.

**What replaces it: shape.** The check that survives in
`tests/boundaries/test_the_facade_does_not_orchestrate.py` is
`test_no_function_in_the_facade_holds_a_body_of_work` — no function in the facade may exceed six
statements, counted recursively through compound statements so a `for` loop does not score 1. That
is the assertion that was always carrying the meaning. A facade can double its `__all__` without
breaking it, and cannot smuggle a run loop past it. Size was a proxy; this is the thing.

### What changed

| file | change |
|---|---|
| `tests/boundaries/test_the_facade_does_not_orchestrate.py` | `MAX_LINES` and `test_the_facade_stays_a_surface_rather_than_a_module` deleted. The reasoning is kept in place, as a note, because the next person to reach for a line cap should meet the three measurements rather than re-derive them |
| `docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md` §3 5단계 | the "no file in `flow/` exceeds 800 lines" acceptance is struck and replaced with the shape criterion it was standing in for: the four dispatch seams each in their own file, and no rule-named method left on `SimulationFlow` |
| same, §5 진척 지표 | `find … | sort -rn | head -5` stays. It is still measured — it is just read as an **observation**, not a threshold. A number worth watching is not the same as a number worth failing a build over |

### What was deliberately NOT removed

`tests/extension/test_authoring_contract.py:47` caps an **emitted scaffold body** at 40 lines. It is
a line count and it stays, because it is not an acceptance criterion about internal structure — it
is an assertion about the artifact a user copies to start work, where length *is* the defect. Its
failure message says so: *"which usually means framework ceremony came back."* The
`gjc-handoff/README.md` §7.1 record of two reverted scaffold migrations is what that guard exists
for. **Flagged here rather than removed silently, so the owner can extend the ruling if intended.**

The deferred-import ceiling in `test_a_deferred_import_states_its_reason.py` also stays. It counts
hidden cycles, not size; the number means what its name says.

## Part two — four issue files now say what the tree says

The campaign closed work without closing the issues that asked for it, and in one case recorded a
closure it had not earned. Found by auditing all 49 issue files against the implementation records.

| issue | was | is |
|---|---|---|
| `043` | "open when filed" | **CLOSED** by record `108`. `references_to` moved inside `_exclusive()`; the acceptance was a concurrency test that fails on the pre-fix tree first |
| `030` | "half closed" | **CLOSED**, both items. Record `114` ruled that `cli.usage` **is** inside the six-field envelope guarantee |
| `048` | "open" | **CLOSED**, docs-only. `SKILL.md` now prices registration and reading in one place |
| `034` | (silently assumed closed) | **re-marked STILL OPEN**, with the reason — see below |

### `034` is the one that matters, and it is a process finding

Step 10a's acceptance had two clauses. *"All blocks present for a simulation"* landed. *"Two runs at
different execution conventions produce records that differ in `execution`"* did not:
`_RUN_FIELDS` (`flow/run_records.py:67`) has no `execution`, and the `contract` block it does carry
is the constraint report from `flow/records.py:100`, which answers a different question. Record
`115` closed Step 10a without mentioning issue 034 at all.

Nothing went red, because **no test named the clause — it lived only in the plan.** That is this
campaign's own escalation gate item 5 (*"any step whose acceptance cannot be stated as a metric
delta or a test"*) failing in the one direction it was not watching: the clause was stated as prose
about two hypothetical runs, and prose cannot fail.

An erratum is appended to record `115` where the claim was made, and `034` states what Step 10a
genuinely bought it: a kind-discriminated field set with a versioned schema and a reader that
refuses a major-version mismatch, so `execution` is now an additive field rather than a shape
change. **The plumbing exists; the field does not.**

## Part three — the read-cost sentence, and the two issue files that were mid-air

`SKILL.md`'s registration sequence gains the cheapest item on issue `049`'s list, which `049` itself
names as worth doing even if nothing else on that list is: **the read cost of a dataset scales with
the cells its window admits, and a long/EAV registration multiplies those cells by its key width.**
It is paired with `048`'s registration number (`rows x key width`, ~50M row-keys/second) because the
two are only useful together — one is paid once and is not the problem, the other is paid on every
evaluation and is.

The guidance still tells an author to register at the vendor's grain. That advice is not withdrawn
and should not be: which of a name's many rows on one date a research question means is a research
decision. What changes is that the bill is now quoted **before** the schema is committed to, rather
than discovered afterwards.

Also committed here: issue `045`, re-measured from 410x to **150x** and renamed accordingly, and
issue `049` itself, both of which were sitting uncommitted in the working tree. `044`'s
cross-reference to `049` had been spliced into the middle of a sentence and is repaired.

## Validation

| gate | result |
|---|---|
| `uv run ruff check src/` | **All checks passed** |
| `PYTHONUTF8=1 uv run pytest tests/boundaries tests/extension tests/qa -q` | **203 passed**, 1 deselected |
| `PYTHONUTF8=1 uv run pytest tests/ -q` | **1497 passed**, 14 deselected in 169.57s |

**1497, not 1498, and the missing one is the deleted line-count test.** Baseline on `develop`
before this branch was measured at 1498 for exactly that reason. No test was skipped, weakened or
xfailed to reach this number — one gate was removed by ruling and the count follows it down. Stated
because a suite count that goes *down* is the shape a weakened acceptance also has, and the campaign
has that failure on file twice.

## Remaining work

- **`034` needs its field.** The vocabulary for an execution convention is the open half; the record
  shape is ready for it.
- **Step 11's remainder** is now unblocked in the sense that the contradiction is gone, but record
  `117`'s *other* blocker stands and is the harder one: the refusal-code inventory resolver folds
  f-strings only through same-file, module-level constants, so splitting `Workspace` from
  `_workspace_error` silently removed 37 codes with a green suite. **That is a fact about the
  inventory tooling, not about the split**, and it should be fixed there before the split is retried.
