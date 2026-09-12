# 193 — Registration and the conformance it proves live together, and two modules find their layer

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M4;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:**
`tests/boundaries/test_the_layers_hold.py`, which held `("extension", "testing")` open for this
milestone.

## Why

**The fourth cycle, and the only one nothing was hiding.** `extension/registration.py:24` imported
`vqapr.testing.conformance`; `testing/conformance/runner.py:47` imported `vqapr.extension.loading`.
Both at module scope, neither deferred, and the package has been importable the whole time — because
the two statements name different *modules*, and the order they happen to load in works. Nothing was
wrong until someone added a third edge, and then it would have been an `ImportError` in a place that
had not changed.

The direction was also backwards. Registration is the door canon 10.2 describes -- *"enter through
the same door and pass the same conformance"* -- and conformance is what the door proves. A suite
the door calls cannot sit above the door.

`testing/` existed for a real reason, but a packaging one: canon 10.3 ships the suite instead of
keeping it in `tests/`, so a user can prove their own component before registering it rather than
reading our test suite to guess the contract. That argument says the code must be **installed**, not
that it must be in a package named for testing. `vqapr.public` re-exports `conformance`, which is
how a user actually reaches it, so the module's own path was never the thing keeping the promise.

**Two modules the layer table could only place by guessing.** `authoring_lookback.py` and
`inputs.py` were flat modules at the top level whose names described neither their altitude nor
their subject.

## What

**`testing/` is deleted; the suite is `extension/conformance.py`.**

`testing/conformance/runner.py` moves verbatim, and the package `__init__`'s argument — the canon
10.3 shipping rationale — is folded into the module docstring rather than dropped, together with
what the move fixed. `tests/testing/test_conformance.py` moves to `tests/extension/`. Two
`__init__.py` files and two directories go with it. `vqapr.public:151` re-exports `conformance`
unchanged, so no user-visible surface moved.

**`authoring_lookback.py` -> `extension/lookback.py`.** The name put it beside the authoring
contract, but it declares nothing an author subclasses: it answers what `vqapr new` should emit,
its only caller is `cli/new.py`, and it already read `ComponentKind` from `extension/`. It belongs
beside `scaffold.py`, which is what it serves.

Record `190` proposed this move on its own and it was deliberately **not** taken then — the owner's
instruction was that a single-file relocation gets overwritten once the boundaries are redrawn, so
it should happen inside the campaign or not at all. This is that campaign.

**`inputs.py` -> `domain/inputs.py`.** It imports `domain.errors` and nothing else, and its readers
sit at three altitudes: `cli/` (ten call sites), the declaration layer, and now
`extension/lookback.py`. A module every layer reads and none owns is what `domain/` is for. At the
top level the layer table had to assign it a number by guessing which of its readers mattered most.

**`OPEN` loses `("extension", "testing")`**, and `testing`, `authoring_lookback` and `inputs` leave
`LAYERS` because the nodes are gone. Seven edges remain: four for M5, three for M6.

## Trade-offs

**`vqapr.testing` is gone as an import path.** It was the only thing under that name, `public`
re-exports what it offered, and `tests/characterization/refusal_codes.py` — which drives the
conformance refusals to build the runtime half of the baseline — needed one line changed.

**`extension/` now holds six modules, one of which users are told to call.** That is a genuine
mixing of audiences: `loading.py`, `registration.py`, `fingerprint.py` and `component.py` are
internal, and `conformance` and the scaffold's output are not. The alternative was a package whose
only member imported the package it is called by, and the boundary tests could not tell the
difference between that and a mistake. The docstring says which is which.

**A `domain/` module named `inputs` sits next to `domain/errors`.** The two are one subject —
`InputError` is a refusal — and folding it into `errors.py` was the other option. It stays separate
because `errors.py` is 535 lines about the framework's own failure vocabulary and this is 203 about
the user's files being wrong before the framework is reached, which is a different question with a
different `Stage`.

## Validation

- `uv run ruff check src/` — clean; `--fix` scoped to `src/`.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**.
  This milestone moves the module that raises the conformance refusals *and* the module that raises
  every user-input refusal, so the gate is doing real work here.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after tightening. Before tightening it failed
  as designed: *"these OPEN entries no longer violate anything: [('extension', 'testing')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 328 s: identical to the pre-campaign baseline.
