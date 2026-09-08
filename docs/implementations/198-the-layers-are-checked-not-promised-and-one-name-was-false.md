# 198 — The layers are checked rather than promised, and one name was false

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M8, closing;
`docs/refactoring/2026-09-08-the-layering-campaign.md`). **Reported by:** the campaign closing
itself — `OPEN` empty, and the documents that still described the tree it started from.

## Why

Three things outlived their subject.

**`pyproject.toml` gave a false reason for declining an import-linter.** The comment made two
arguments and only the first survives:

> module layout is non-normative (PRD 0.1), so a tool contract must not drive type placement.
> Every boundary that matters is enforced by the absence of a path ... **and a misplaced type
> surfaces as a circular import, which Python reports without a tool.**

The campaign measured four package cycles at 0.8.0 and Python reported none of them: two were
deferred into function bodies, one was held open by a `TYPE_CHECKING` import, and one was
module-level in both directions and merely happened to load in a working order. A fifth —
`extension/` writing to the workspace it sits below — was not in the diagnosis at all and surfaced
only once the layers were written down. `tests/boundaries/test_a_deferred_import_states_its_reason.py`
had already recorded that the premise was false; the file it contradicts kept asserting it.

**One module's name had become false, not merely dated.** Record `196` moved the half of
`extension/registration.py` that writes down to `project/registration.py`. What stayed prepares a
`ComponentRef` and proves it conforms. It registers nothing.

**The manifest still pointed at a finished campaign** and a doc still named a module by a path that
had moved.

## What

**`pyproject.toml`'s rationale is rewritten.** The non-normative-layout argument stays and is the
reason the replacement is a test in this repository's idiom rather than a tool's config file. The
"Python reports it" half is retired with the measurement that retired it, and the comment names
what took over: `tests/boundaries/test_the_layers_hold.py`. The stale `flow/views` reference in the
same sentence becomes `flow/engine`.

**`extension/registration.py` -> `extension/prepare.py`**, with the module docstring's self-naming
line updated and the two prose references in `extension/conformance.py` corrected — one of which
now names both halves, since the door is `prepare.py` proving and `project/registration.py` writing.

`tests/boundaries/test_internal_holds_no_extension_authority.py` guards the four modules record
`110` promoted out of `_internal/extensions/`, by name. The name in that tuple changes and the
comment says why: the property is that the authority lives in `extension/` and holds a real
implementation, and a rename does not undo record `110`.

This is the only rename the campaign took, and the campaign document says what it declined and why:
`flow/declaration/` now holds three modules that declare nothing, and `flow/roster.py` is a project
read wearing a flow path. Both names are **incomplete**; neither is false, neither violates a layer,
and both have importers. A rename for a name is churn.

**`docs/design/agent-first-surface.md`** gets one annotation rather than a rewrite. The sentence is
about what record `112` did, so `vqapr/declarations.py` stays and *"(now
`vqapr/project/registration.py`, record `194`)"* is added beside it — the same treatment record
`194` gave the `CEILING` docstring's history section. History that names a path is not a stale
reference to fix.

**`.agent/project.yaml`** points `active_campaign` at this campaign and records what it did.

**The campaign document is closed** with a before/after table, the two findings worth carrying
(record `117`'s constraint retired by measurement; `extension -> project` found only by the written
table), and what was deliberately not done.

**M7 is cancelled, and the diagnosis that proposed it is marked wrong.** The campaign's section 1.5
claimed `analysis/` and `report/measure.py` were two packages doing one job. Checking the four edges
before starting showed the opposite: `report/measure.py` **imports** `fill_summary`, `drawdown`,
`returns` and `correlation` from `analysis/`. They are layered, not duplicated — `analysis/` is the
primitive toolkit and `report/` composes it into documents — and `analysis/` has independent
consumers in `cli/run.py` and six user-facing exports in `vqapr.public`. Merging would have closed
no cycle, fixed no violation, buried a user toolkit inside the framework's own document builder, and
broken `vqapr.analysis.*` for nothing.

## Trade-offs

**`CEILING` is not lowered.** It is 10 and the real count is 10, so the ratchet is already tight.
Worth stating because M8 was planned to lower it: the campaign removed two deferred imports at
record `191` and lowered it then, and the `TYPE_CHECKING` import it removed at record `192` was
never counted — that ratchet walks function bodies, so a module-scope `TYPE_CHECKING` cycle is
invisible to it. That gap is now covered by the layer table, which counts every import statement
including the ones inside `if TYPE_CHECKING`.

**`data/scan.py` stays at 1,471 lines.** It splits cleanly in three — registration-time proofs,
run-time reads, connection and session core — and its eight refusals are all literal, so the split
is safe. It is not done, because it is neither a cycle nor a layer violation, and this campaign held
size questions separate from layering ones every time it met one (`store.py` at 957,
`project/registration.py` at 1,276). Making an exception in the final commit would retroactively
make that separation arbitrary. It is a named, measured candidate for its own task.

**The two pre-existing failures are still there.**
`tests/agent/test_the_release_records_what_it_ships.py` has failed for the whole campaign and
predates it — confirmed at record `190` against a stashed tree. It is the release-only
`_shipped.json` check, which `.agent/project.yaml` describes as *"meant to fail"* between releases,
running under the default `test` command where that description does not apply. Left alone
deliberately: it is unrelated to layering and fixing it inside this campaign would mix subjects.

## Validation

- `uv run ruff check src/` — clean.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/boundaries/ tests/characterization/test_refusal_codes.py -q` — 47 passed.
  Two failed first: the record-`110` guard naming `registration.py`, fixed above.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two described above.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 316 s: identical to the pre-campaign baseline, across all nine milestones.

**The campaign's own numbers, measured at close:**

| | `4fdd46fb` (0.8.0) | now |
|---|---|---|
| package cycles | 4 | **0** |
| flat top-level modules | 9 | **1** (`public.py`) |
| graph nodes | 22 | 18 |
| declared-legal layer violations | 11 | **0** |
| function-local `vqapr` imports | 12 | 10 |
