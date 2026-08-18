# 011 — Run the enhanced index through the spine

## Why this exists

Record 010 shipped the construction and publication path and then said, in its own words, what it
did not ship: the enhanced-index showcase never ran through the execution spine, never proved
multi-input subscription through `DataRequirement`, and its "replay" was a consistency check over
the journal its own loop had written. Three deliverables of one story were recorded as open.

Closing them was not decoration. The first real run through the spine found a defect that no test
in the suite could see: **`publish_run_allocation` could not consume a real run's callback
evidence.** The Flow records its decision as the accepted pending item (`AcceptedIntent`), which
carries the intent alongside the execution target it was bound to; the writer read `.targets`
straight off `decision`, which succeeds for every hand-built stand-in and fails for every genuine
callback. The suite was green because every test — including the one that existed specifically to
make field names load-bearing — built the wrong shape.

## What was built

| Deliverable | Location |
|---|---|
| Accessor from a finished run to its callback evidence | `src/vqapr/flow/simulation.py` (`callback_evidence`) |
| Publication accepts the wrapper a real callback records | `src/vqapr/flow/materialize.py` |
| Public surface for allocation construction and shipped constraints | `src/vqapr/public.py` |
| Regression tests for both, including the real accepted-intent shape | `tests/flow/test_publish_allocation.py` |
| Pinned public export list | `tests/boundaries/test_public.py` |
| Showcase rebuilt as two real runs | `showcases/show_005_enhanced_index/` |

## How it works

**One accessor, no second authority.** A run's decisions live on its state root, in lifecycle order.
`callback_evidence(result)` returns every `CallbackEvidence` that root carries, declines included,
because whether a decline publishes nothing is the publisher's rule and not the accessor's.
Reconstructing evidence from `SimulationResult.occurrences` would have meant re-deriving what the
Flow already stamped.

**The writer unwraps what the Flow wrote.** `publish_run_allocation` now resolves the economic intent
out of an `AcceptedIntent` before reading targets. The regression test constructs the real wrapper —
a real `OperationOccurrence` and a real `ExactExecutionTarget` — so the shape is pinned to what the
spine produces rather than to what a test finds convenient.

**The public surface now reaches the capability record 010 shipped.** `optimize`, the allocation
input contract, and the shipped-constraint path resolver were reachable only through internal module
paths, which meant the documented surface could not express an enhanced index at all. They are
exported and pinned. The showcase's own components import from `vqapr.public` only, which is what
makes it evidence about the product rather than about the repository.

**The showcase is two runs, not a script.** An alpha run on the Academic profile emits a signed
dollar-neutral intent each session; its callback evidence is published as `alpha_allocation`; an
enhanced-index run on the KRX profile declares `benchmark_weight_daily` and `alpha_allocation` as
ordinary `DataRequirement`s and combines them inside one point-in-time window. The 08:30 alpha
decision stamps itself from its own reads, and the 09:00 index callback is the consumer that can see
it — the chain is enforced by the derived stamp, not by ordering the script.

**The bounds come from the registered constraint set.** The index Strategy passes
`context.constraint_bounds` — what the registered `NoShort` and `SingleNameCap` projected for that
occurrence — straight into `optimize`. There is no second copy of the cap rule in the showcase, so a
regression in the shipped constraint changes the showcase's numbers instead of hiding behind a
local reimplementation.

**The replay is independent.** Cash and every position are rebuilt from the committed fill journal
and compared to the committed `AccountSnapshot`. The two are separate records of the same history;
a mismatch aborts.

**Monitoring is read back, not assumed.** Registering a constraint set proves nothing by itself. The
set is enforced at the decision -- an intent failing its projected bounds stops the run, so 21
completed rebalances are 21 compliant intents -- while monitoring is evidence over each marked
account version and never gates anything. Reading it back is what turned an implicit claim into a
result: on 10 of 21 monitored occurrences the marked book sits above its single-name ceiling.

That is a property of the constraint, not a defect. `single_name_cap` is defined relative to the
index, and the index moves: the book is built at 09:00 against the previous session's weight and
marked at 16:30 against the current one. On 2026-04-02 the marked weight is `0.32670` -- the
previous session's ceiling `0.32680` less whole-share rounding -- against that day's `0.32300`. A
benchmark-relative cap is held at each decision, not continuously between them. `no_short` has no
moving reference, so a marked short position would mean the long-only account authority failed;
that case aborts, and it never fired.

## Trade-offs

**The pinned name is the least-slack holding.** Freezing the alphabetically first name froze a name
that never bound, so the release path never ran and the guard was demonstrated by its absence.
Pinning the holding with the least slack against its own upper bound is the honest choice — it is
the position that tests the conjunction `l ≤ w ≤ u ∧ w = w₀` hardest — and on the committed slice it
produces both outcomes: 10 freezes returned verbatim, 10 refused as out of box.

**Determinism is checked, not asserted.** The whole pipeline runs twice into separate projects and
both the reported outcome and the artifact digests must match. Two replicates cost a second run; the
alternative is a determinism claim nobody executes.

**`callback_evidence` returns declines.** A caller who wants only accepted intents filters. Dropping
them here would have made the accessor's output depend on a policy that belongs to the publisher.

## Deliberately not built

No `SimulationResult` → publication convenience wrapper: publishing is a separate decision with its
own spec, and folding it into `run()` would put a write on the run path. No export of
`CallbackEvidence` itself — the showcase passes it through and never inspects it, so exporting the
type would widen the surface without a caller. No new agenda, role, or execution semantics: both
runs use the existing four roles and the existing `SAME_DAY` fill convention.

## Validation

- `uv run pytest -q` — **292 passed** (from 288 at the milestone start). The four new tests cover
  the accessor's ordering and its refusal, its hand-off into publication, and the real
  accepted-intent shape; the widened export list is pinned by the existing boundary test, which was
  extended rather than added to.
- `uv run ruff check src tests scripts showcases` and `ruff format --check` — clean, 188 files.
- `uv run python showcases/show_005_enhanced_index/run.py` — 22 sessions, 21 callbacks, 21 published
  alpha occurrences, two subscribed allocation inputs, **10 freezes returned verbatim and 10
  released** by the optimizer's own refusal, 21 monitored occurrences with **0 marked short
  positions and 10 cap-drift findings** (worst excess 0.0078 over a 0.3212 ceiling), **67
  whole-share fills**, commission 227,197.80 and sale tax 276,818.20, journal replay equal to the
  committed Account at 518,988,184.00, final NAV 1,168,772,684.00, and two replicates producing
  identical SHA-256 digests.

## What is still open

- A benchmark-relative cap cannot be held between rebalances while the benchmark moves. Whether the
  ceiling should be pinned at the decision, re-based at each mark, or given an explicit drift
  allowance is a product decision, not a code fix, and nothing here makes it.
- The coverage-scoped weight-sum tolerance never binds against the committed fixture, so its
  allowance is still asserted only by restating its own formula.
- ~~A caller passing `cash_range=(0, 1)` can be refused on a problem whose exact answer is
  `cash = 0`, because of a quantization residual at the lower edge.~~ Closed by record 012.
- `frozen` still models both "cannot trade" and "caller pinned this"; refusing the whole solve is
  right for the second and arguable for the first.
