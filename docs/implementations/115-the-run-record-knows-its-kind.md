# 115 — The run record knows its kind, and the VB002 review is answered

**Closes:** Step 10a of the approved structural plan, and findings 1–10 of the independent VB002
architecture review.
**Branch:** `step-10a-the-run-record-knows-its-kind`.

## Part one — the record's shape

`RECORD_FIELDS` was a flat 8-tuple: the record could describe exactly one kind of thing. It is now
kind-discriminated — `RECORD_FIELDS_BY_KIND` with `record_fields(kind)` — and `SCHEMA` bumps
`vqapr-run-record/v1` → `v2`. The writer stamps `kind` before the answers.

Both kinds are declared here although only `run` is written; `MATERIALIZATION_KIND` gets its field
set now so the discriminator has two real branches rather than one and a promise, and so record
`116` adds a *producer* rather than also changing the reader. The two kinds deliberately share
`run_id`, `source_digest`, `declared_digest` and `period`: a reader asking "which declarations
produced this" should not need to know which kind it holds.

`finish(record, *, kind=RUN_KIND)` defaults, which is what lets a shape change land without touching
a single call site.

## Part two — the reader-side check, which is the point of the story

Three things were true at once: `read_record` was `json.loads` with **no schema branch at all**;
`cli/show.py` read every field with `record.get(field)`; and `RECORD_FIELDS` was flat. So a reverted
reader handed a new-shape record **did not refuse** — it rendered what it recognised and dropped the
rest — and a new reader handed an old record rendered the new fields as `null`, indistinguishable
from "this run genuinely had none". *"A reverted reader refuses loudly"* was an assumption.

`_require_known_schema` makes it a property. It compares the **major** version only: a minor bump is
additive change a `.get` reader survives by design, while a major bump means a field it thinks it
understands may now mean something else. `v1` records are read as runs, because that is what every
`v1` record is — refusing them would make the bump a breaking change for every stored run.

A shape check landed in front of it. `read_record` returned a non-mapping payload as-is, so
`record["account"]` raised `TypeError` two frames from the corrupted file.
`tests/qa/test_run_records_survive_and_race.py` pinned that and said in the pin that adding a check
would be an improvement; the schema check cannot read a payload with no keys, so it is added and the
pin is updated.

`record_view` branches on kind. A flat projection would render a materialization as six nulls and
drop everything it answers. `kind` is surfaced alongside the fields rather than among them: `schema`
says how to parse the file, which is the reader's problem; `kind` says what the file is about, which
the caller needs.

## Part three — answering the VB002 review

An independent architecture review of Steps 7–9 returned **CONCERNS / REQUEST CHANGES** with ten
findings. Two were P1 and both were mine. All ten are addressed here.

### Finding 1 — record 113 claimed two tests that did not exist (HIGH)

The worst error in this campaign so far. Record `113` stated *"Two tests: one that a damaged pointer
no longer costs the record, one that a `TypeError` still escapes"* and tallied the file at "7 passed
(was 5; +2 for R1)". **Neither test existed.** The `cat >>` heredoc that was to append them failed
with `Bad file descriptor`; the file's pre-existing parametrised count of 7 was mistaken for
evidence they had landed; and the fix for the batch's most severe defect shipped **entirely
unexercised**. Nothing would have failed if `except VqaprError` were widened to `except Exception` —
the exact over-broad catch `docs/issues/042` exists to prevent.

`tests/flow/test_a_completed_run_survives_a_broken_roster.py` now exists: five tests, including one
that reads the source to assert `roster_report` is not evaluated back inside the guard, because
every behavioural test would still pass if it were. Record `113`'s validation table is corrected
below.

### Finding 2 — `roster: null` stated a falsehood (HIGH)

R1's fix absorbed the failure as `None`. But `flow/records.py` and `flow/run_records.py` both define
`roster: null` as *"the run never knew the categories"*, and `run` calls `registered_roster` **before**
`flow.run()`, which refuses an unreadable pointer outright — so **any run reaching the record did read
its roster**. `None` wrote a falsehood into the frozen artifact a cold process reads, while the
ephemeral CLI envelope told the truth: the two disagreeing about the same run. It is
`{"known": true, "stale": true, "note": ...}` now, the shape `cli/run.py` already reaches for the
same reason.

### Findings 3 and 4 — two gates were defeatable, and one had a live violation

`test_the_frozen_cluster_gains_no_callers` matched `node.module` only, so **`from vqapr import
venues` was invisible** — and `simulation.py:30` is exactly that, a live inherited edge into frozen
`venues.py` recorded in neither the test nor `docs/design/agent-first-surface.md`, which still said
`venues.py` was imported only by `_internal/venue_bridge.py`. Both are corrected; neither end is a
new caller, but the list was not the record it claimed to be.

`test_the_facade_does_not_orchestrate` read `tree.body`, so **class methods were never visited** —
re-adding `_FrozenCatalog`, one of the things record `111` moved out, with a large method would have
passed. And `len(node.body)` counted a `for` loop as one statement, contradicting its own docstring's
"no room for a run loop". Now `ast.walk` plus a recursive count, and `MAX_LINES` gets the
exact-equality companion its sibling ratchet already had. **Verified by injecting a class with a
compound-statement method: both assertions fire.**

### Findings 5, 7, 8 — my own move artifacts

`declarations.py` carried `_COMPONENT_KINDS`, `DECLARE_STAGE` and `SECTIONS` **twice**, byte-identical,
35 lines — introduced by Step 8's move and undisclosed. Ruff cannot see it (`F811` does not cover
module-level assignment). Deleted.

`flow/records.py`'s docstring stated record `113`'s decision *and its refutation* in consecutive
clauses — "a run record is a flow artifact, and this is where it belongs" followed by unrevised
`evidence/`-era text saying it is evidence production — and inverted the rename direction. Corrected.

`AUTHORED_KINDS`'s docstring stayed in `cli/register.py` as an inert string when its constant moved
to `declarations.py`, which violates this campaign's own rule that docstrings move with code.
Reunited.

### Findings 6, 9 — the agent-facing contract

`cli.usage` emitted `"source": None` where every other refusal emits an object, so
`failure["source"]["file"]` raised `TypeError` on that one refusal alone. It emits the object with
null members now. `SKILL.md`'s closed-topic paragraph gains the `cli.usage` null case, and
`test_refusal_envelope_six_fields.py`'s module docstring — which still argued in the present tense
for a defect record `112` fixed, citing a moved file — is rewritten to the resolved state, with the
`BROKEN:` heading removed from a test whose body always asserted success.

### Finding 10 — deferred imports carried past the cycle that justified them

Five function-local imports moved verbatim out of `vqapr.public`, where the facade sits above
everything. In `flow/` that justification does not hold, and `flow/orchestration.py` already imports
`vqapr.workspace` eagerly. Hoisted, and `CEILING` lowered **104 → 99** in the same commit, which is
what that ratchet is for.

## Validation

| check | result |
|---|---|
| `tests/flow/test_the_run_record_knows_its_kind.py` (new) | 7 passed |
| `tests/flow/test_a_completed_run_survives_a_broken_roster.py` (new, finding 1) | 5 passed |
| `tests/boundaries/` | 37 passed, with both defeats closed and re-proven |
| deferred-import ceiling | **104 → 99** |
| fast suite | **1487 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |

**One flake, disclosed rather than hidden.** `test_five_processes_racing_the_same_run_id_refuse_rather_than_interleave`
failed once during this work with two winners. Re-run 6 times with these changes and 6 times with
them stashed: 12 of 12 passed. It is a load-sensitive pre-existing race in the run-id lease, and two
QA agents were saturating the host at the time. Not a regression, and not silently dropped.

## Correction to record 113

Its validation table claimed
`tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py | 7 passed (was 5; +2 for R1)`. That
line was false: the file had 5 test functions before and after, collecting 7 through pre-existing
parametrisation, and R1 had no tests at all. The real tests are in this record's branch.
