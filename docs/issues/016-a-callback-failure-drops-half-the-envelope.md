# 016 — A callback failure drops half the envelope the skill guarantees

**Status:** **closed** by `docs/implementations/088-a-callback-failure-carries-the-whole-envelope.md`
(branch `fix/016-callback-envelope`). A callback failure now carries all six fields; `requirement`
describes the author's callback rather than the framework's guard, and `fix` names where to look.
No new `ExplainTopic` was needed - the existing `component-contract` and `publication` topics cover it.

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. This is the cross-cutting half
of **F-005**, **F-006** and **F-007** in that log — the reporter's own words: *"Three further
entries are the same defect three times."*
**Touches:** wherever `simulation.callback.*` failures are assembled — the guarded boundary around
`decide()`; `src/vqapr/_internal/models/agent_first.py:356`, `src/vqapr/authoring.py:670` are the
two raise sites this journey reached.

## The guarantee

The installed skill states it without qualification:

> Every entry carries `code`, `source`, `requirement`, `observed`, `fix` and `explain`

and tells the reader which to use first:

> read `fix` first. It is the sentence that fixes *this* occurrence

## What arrives instead

Both failures raised inside the simulation callback during this run:

```json
{"code": "simulation.callback.intent.ValueError",
 "observed": "invested must be greater than zero and no greater than one",
 "requirement": "the guarded boundary must complete without raising",
 "example_total": 0, "examples": []}
```

```json
{"code": "simulation.callback.intent.ValueError",
 "observed": "decide() emitted undeclared diagnostic tables: ['ff3.formation']",
 "requirement": "the guarded boundary must complete without raising"}
```

**No `fix`. No `explain`. No `source`.** Three of the six, and the missing one is the field the
skill names as the one to read first. `requirement` degrades to *"the guarded boundary must complete
without raising"*, which is a statement about the framework's own plumbing rather than about
anything the user did.

## Why it is worth a file of its own

The gap is **specific to `simulation.callback.*`**, and that is what makes it fixable as one thing.
The same journey reports registration failures and `check` failures carrying all six — issue 015
quotes `check.execution.not_after_decision` complete with `fix`, `explain`, `source` and 85
`examples`, and calls it the best-formed failure of the entire run. The package knows how to build
these. One boundary does not.

It is also the boundary where the deficit costs most. Registration and `check` failures are cheap to
retry; a callback failure has already spent the run assembly, and it is the only class of failure
that arrives after `check` has returned `ok:true` on five phases (see 018 and 019 for why `check`
cannot see either of these).

The follow-on cost is recorded as **U-001** in the same log, and it is the strongest argument here.
With no `explain` topic to follow, the reporter went to `.vqapr/diagnostics/<correlation_id>.txt`,
which is a full Python traceback ending in `authoring.py`, line 670. The package's own failure
artifact became the single strongest invitation to read the package source that the run produced —
*"stronger than any gap in the docs, because it is specific, local, and looks like something I was
handed on purpose."* The traceback is right to be there. The missing `explain` is what made it the
only remaining lead.

## Two things to settle, not one

1. **Can the boundary carry `source` at all?** For a user-code exception the honest `source` is the
   user's file and line, which the diagnostics traceback already has. Naming it in the payload is
   the whole of U-001's remedy and it is probably mechanical.
2. **Where does `fix` come from for an exception the framework did not raise?** A generic
   `fix` ("read `.vqapr/diagnostics/<id>.txt`, then correct the named line") is worth more than
   absence, but the two failures above are both raised *by the package* inside user code, and both
   have a specific correct answer — see 018 and 019, which propose them. The rule worth writing
   down: a `ValueError` the package itself raises inside the callback is not an opaque user
   exception and should not be reported as one.

## Do not fix this by widening `requirement`

`"the guarded boundary must complete without raising"` is true and useless. Replacing it with a
longer sentence about boundaries does not help; what the reader needs is the three absent fields.
