# 077 -- a judgment that could not look is reported as passed, because the helper swallows before the dispatcher can block it

**Status:** **CLOSED 2026-09-04 by record `153`** (one-shape campaign Step 2b). No helper in
`flow/judgments.py` catches on behalf of a judge any more: the agenda is reached through a call
whose failure re-raises to every asker, `datasets` is dispatched one judge per member (named
`datasets[<component-id>]`, which is where the reader learns which member), and the execution,
weights and `_instant` helpers let their exceptions reach the dispatcher. Under D7 the defect is
named twice, and `tests/cli/test_a_judgment_that_could_not_look_is_not_passed.py` pins both halves.
The three smaller sites in the last section are recorded, not fixed. Found 2026-09-04 by a full audit of every exception handler under `src/vqapr`
(153 sites: 143 handlers plus 10 `contextlib.suppress`), run at the owner's request after the
`076` work. Reproduced twice, from two independent causes. This is the judgment-layer form of the
defect `076` closed at the message layer: `076` was a refusal that lost the reason it refused,
this is a judgment that lost the fact that it never ran.

**Touches:** `src/vqapr/flow/judgments.py:88-105` (the dispatcher's `blocked` mechanism, which is
correct, and which the swallowing defeats); `:190` `_decide_agenda` (`except (VqaprError,
ValueError, TypeError)` -> `return None`); `:207` `_judge_execution_ordering` (`except VqaprError`
-> `return []`); `:268` `_judge_datasets_and_fields` (`except (VqaprError, TypeError, ValueError)`
-> `continue`); `:454` `_judge_account` (`except (VqaprError, TypeError, ValueError)` -> `return
found`); `:146` `_instant` (`except ValueError` -> `return None`); and the consumers of the
report, `src/vqapr/cli/check.py:110-168` (the phase loop that builds `passed`/`blocked`) and
`src/vqapr/cli/run.py:96` (`_refuse_if_judged`, which treats blocked as refused).

## What happens

`judgments()` has exactly the right mechanism for a judgment that cannot answer, and its own
comment states the principle better than this issue can:

> One judgment failing to ANSWER must not silence the others -- letting the exception abort the
> loop would quietly restore the stop-at-first behaviour this verb exists to replace. But
> **swallowing it silently is the worse half of that trade: the judgment did not find nothing, it
> could not look**, and a run nothing was proven about would then report as clean and ready. So it
> is recorded as BLOCKED.

The dispatcher wraps each judge in `try/except Exception` and records a blocked entry. Five
helpers catch **inside**, before the exception can reach that wrapper, and return an empty result.
An empty result is indistinguishable from "this judgment asked its question and found nothing
wrong", so `check` reports the judgment as **passed**.

Reproduced. A workspace registered normally, then the `prices` parquet the run derives its
sessions from is corrupted (`register` has already accepted it; nothing re-validates a source file
afterwards):

```
vqapr check r1
{"ok": false, "passed": ["workspace", "run", "judgments"], "blocked": [],
 "codes": ["source.scan.distinct.unreadable"]}
```

`judgments` is in `passed`. `derived_agenda` raised, `_decide_agenda` returned `None`,
`_judge_execution_ordering` then hit `if agenda is None: return found` and returned empty -- so
**AC-C5, the look-ahead judgment `015` exists for, never ran**, and nothing in the report says so.
`blocked` is empty, which asserts that every judgment was answerable.

The same report comes from an unrelated cause: a dataset whose `available_at` column is a naive
`TIMESTAMP` rather than `TIMESTAMPTZ` also yields `passed: [..., "judgments"], blocked: []`, with
the single failure coming from preflight.

## Why this matters even though the run is refused

In both reproductions the run does not execute: the `preflight` phase runs after `judgments` and
raises. So the helpers' shared defence -- each carries a comment saying another judgment or
preflight owns that refusal, and reporting it twice would be worse -- is, as an outcome, true
today. Two things are still wrong.

**The report makes a false statement.** `check`'s own module docstring sets out the property:

> Dependent checks are reported, not silently dropped. [...] Those are reported as `blocked`,
> naming what blocked them, so the reader can tell "this passed" from "this never ran" from "this
> failed".

That is the distinction the verb is FOR, and it is exactly the distinction that breaks here. An
agent repairing its own setup reads `passed: ["judgments"]` and concludes the eight judgments were
made. They were not.

**The safety depends on a coupling nothing pins.** `check` is only correct here because preflight
happens to reach every door these helpers decline at. No test asserts that. The day a preflight
check is narrowed, moved behind an early return, or made conditional, `check` answers `ok: true`
on a run whose look-ahead judgment never ran -- which is `015` again, reintroduced silently, and
through a path `015`'s own regression test does not watch.

`_instant:146` is the same shape at a smaller scale: an unparseable timestamp becomes `None`, and
the period judgment then treats "not comparable" the same way it treats "no bound declared".

## What to do

The direction the campaign already takes elsewhere: **let the exception reach the one place that
owns the decision.** Remove the helper-level `try`, and let `judgments()`'s wrapper record a
blocked entry -- `ok` is then false, the judgment is not in `passed`, and the reader is told which
question could not be asked and why.

What that costs, and what has to be settled with it:

- **Double reporting. SETTLED 2026-09-04 by the owner: the envelope carries BOTH.** The helper
  comments are right that the same defect is then named twice: once as a blocked judgment, once as
  preflight's refusal. That is the reason the `try` blocks were written. But a blocked entry and a
  refusal are not the same statement -- one says "this question could not be asked", the other says
  "here is the defect" -- so both belong. `check`'s three-way distinction is restored, and the
  silent dependence on preflight's coverage is removed. The cost accepted is two entries for one
  defect.
- **`_decide_agenda` is shared.** It feeds `_judge_execution_ordering` and
  `_judge_datasets_and_fields`. If it raises, both must block, with the same reason -- not one
  blocked and one passed.
- **A test that pins the coupling.** Whatever is decided, `check` needs a regression test in which
  a judgment cannot answer and the report says so: `judgments` absent from `passed`, an entry in
  `blocked`, `ok: false`. Both reproductions above are ready-made fixtures.

## Related

`015` (check and run disagreeing -- the judgment this silently skips), `012` (the same family),
`076` (the message-layer form, closed by record `152`), and the one-shape campaign's standing rule
that a rule lives in one place.

## Also found by the same audit, not filed separately

Three smaller sites of the same shape, recorded here so the sweep does not have to be repeated:

- `src/vqapr/extension/loading.py:198` `accepts_contract_call` returns **`True`** when
  `positional_arity` cannot introspect either side, and
  `src/vqapr/testing/conformance/runner.py:150` `continue`s in the same case. The arity check is
  fail-open, and nothing says that is intended.
- `src/vqapr/data/store.py:96`: `except TypeError: return grid[0]` widens a lookback window to the
  whole table when the availability column is naive against an aware evaluation time. Its sibling
  for the identical `TypeError`, `src/vqapr/data/scan.py:1039`, declines to answer instead and says
  why ("guessing here must not be what raises"). Currently unreachable through the CLI -- preflight
  refuses a naive `available_at` first -- so this is defensive code pointing the wrong way rather
  than a live defect.
- `src/vqapr/agent/sample/build.py:115`: `except ValueError: continue` drops a row's traded value,
  biasing the liquidity ranking downward for names with dirty rows. Inside `agent/sample/`, whose
  status is itself an open owner question.

The rest of the audit was clean: no bare `except:` anywhere; all three `except BaseException` sites
clean up and re-raise; all ten `contextlib.suppress` sites are cleanup or lock hygiene with a
stated reason; and the two other `pass`/`return value` handlers (`data/datasets.py:275`,
`workspace_document.py:284`) hand off to a better refusal immediately after.
