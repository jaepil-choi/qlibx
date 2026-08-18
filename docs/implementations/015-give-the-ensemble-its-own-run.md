# 015 — Give the ensemble its own run

## Why this exists

Two StrategyModels could each produce a signed allocation, but nothing could combine them. That
blocked `UC-ENSEMBLE-001`, which asks for members to store signed weights, an ensemble to read both
and net at ticker level, and three things to be confirmable from the result: the quantity where one
member's long offset another's short, the final signed weight, and member lineage.

The planning round found that most of the machinery already existed — publication, point-in-time
subscription, two-input combination, weighting and the exact projection all shipped in the previous
milestone. What was missing was smaller than it looked, and one part of it was not on the plan at
all until the user said the empty surface looked strange.

## The obligation nobody had delivered

Architecture §5.2 states that stored run results carry the performance series, that *"member의 실현
성과로 가중을 정하는 ensemble이 그것을 요구한다"*, and that *"별도 장치가 필요 없다"*. §11.7 names
the volatility-inverse-weighting case reading a member run's NAV series.

That is an obligation, and no milestone had met it. Both review lanes upheld a deferral across three
passes on the grounds that adaptive weighting needs the account-history surface; the Critic then
checked §5.2 and reversed its own position, recording that the deferral had been wider than its
justification. The recorder was reframed from netting plumbing into the general capability canon
already described: **a run records what a later run will need to reuse it.**

## What was built

| Deliverable | Location |
|---|---|
| Canon: run record contract, defaults, publication rules, path-dependence framing | `docs/vqapr-architecture.md` §9.2, PRD §5.4 |
| Per-ticker netting measurement | `src/vqapr/portfolio/diagnostics.py` |
| Package-attested provenance and state path on the allocation envelope | `src/vqapr/flow/materialize.py` |
| Run-record publication, the third caller of the shared authority | `src/vqapr/flow/materialize.py` |
| Weight and decision-time account state recorded by default | `src/vqapr/flow/simulation.py` |
| Ensemble scenario, three real runs | `showcases/show_006_ensemble_netting/` |
| Acceptance suite | `tests/acceptance/test_ensemble_netting.py` |

## How it works

**The offset is measured, not inferred.** A net of zero has two meanings the final weight cannot
distinguish: nobody held the name, or two members cancelled exactly. `net_members` reports the long
side, the short side, the offset and the net per ticker, and the offset is what `UC-ENSEMBLE-001`
requires. The return type is per-ticker evidence rather than a weight mapping, so nothing it produces
can be published as an allocation without the Strategy deciding — implementation record 010's ban on
a package-supplied combination helper stands.

**Provenance comes from what the Flow observed.** An intent's own source refs are every source the
window served, so publishing those would have named an observation dataset a member. The envelope
carries what the Flow recorded instead, and a reader identifies members one hop out by whether a
source's own envelope records an allocation operation.

**Run records publish through the one shared authority.** `publish_run_record` is its third public
caller, not a second authority. `available_at` stays derived; `event_time` and `available_at` remain
two columns because PRD §9.4 forbids collapsing them; the five Flow-stamped envelope fields ride as
declared value fields; and several stages of one measurement are columns on one row, never repeated
rows, because the shared authority keys on `(available_at, instrument)` and refuses a duplicate
before exposure.

**Weight and decision-time account state are defaults.** Both are package-computed, so requiring a declaration would make a
package fact contingent on user opt-in. They land under a reserved `vqapr.` table-id prefix that a
Strategy cannot shadow — the table-id level of the guard the envelope fields already apply at the
column level. The account table carries cash and the account
version, **not NAV**: a callback sees a snapshot with no marks, because marking happens on the
due-execution path, so there is no NAV to copy at decision time. Recording cash under the name NAV
would have put a wrong number under a true-sounding name. The boundary review caught exactly that in
the first draft of this milestone, roughly four percent wrong on the committed fixture.

## Trade-offs

**One member never touches memory, by construction.** The path-dependence attestation fires on any
memory mutation, including a counter that never enters the decision — which is what every strategy
template in this repository does, and those are path-*independent* under PRD §5.6. Canon therefore
frames state movement as **necessary but not sufficient**, records both residuals as limitations,
and the scenario carries one memory-free member so the negative case exists structurally rather than
by luck. The showcase confirms it: `state_path` reports `moved` for one member and `constant` for
the other.

**Per-stock realised profit is declarable, not default.** The committed transition computes quantity
and cash with no cost basis, so a partial sale from two lots has no answer without an average-versus-
FIFO rule, a cost-inclusion rule, and partial-sell and sign-flip handling. Including it would have
pulled in the account-history surface the milestone deliberately does not open.

**The recorder was already wired.** Investigation corrected the plan in the safe direction: the Flow
does build an `InvocationRecorder` per occurrence and thread it through publication. What had never
happened was *use* — no `StrategyModel` had declared `tables()`, so no row had travelled that path
from a real run, and every existing recorder test built the recorder directly against the state
object. That is now proved by 84 rows from a real run with the envelope present.

## Deliberately not built

No fifth `ComponentKind`, no gate on `load_constraint`, no `ArtifactRequirement`, no new dependency,
no second publication authority, no package-supplied combination helper, and no portfolio-level
constraints. The ensemble's own budget matching uses `rescale`, so a flexible budget is never
silently made fixed.

## Follow-ups

**R1 — record resolution ergonomics.** A Strategy reaching recorded run data through a
`DataRequirement` works today by dataset id, but nothing helps a caller discover which dataset holds
which table. The shape it needs is recorded here so the data is not stranded; the milestone
deliberately did not build it.

**R2 — per-stock realised profit.** Needs four decisions: the average-cost convention §7.3 already
implies, whether trading cost enters the basis, partial-sell behaviour, and sign-flip behaviour.

It also inherits a **canon defect this run surfaced**. Architecture §7.3 fixes the account-history
record set as including `avg_entry_price` and `realized_pnl`, and justifies that set by asserting
*"위 값들은 commit을 수행하려면 어찌피 구해야 한다"*. The tree contradicts it: `Account.prepare_fill`
computes next cash and next positions and tracks no basis at all. The milestone that opens this
capability must **reconcile that**, not inherit it.

**R4 — the mark-time NAV series.** Architecture §5.2 requires a stored performance series stamped
at its mark instant, and §11.7③ names the volatility-inverse ensemble that reads it. This milestone
deliberately does **not** ship it: a callback sees an account snapshot with no marks, so the only
honest decision-time record is cash. The series needs a recorder where marks exist, on the
due-execution path, stamped through the derived-availability rule rather than copied from the
callback clock. The boundary review caught the first draft recording cash under the name NAV — about
four percent wrong on the committed fixture — which is why this is a named follow-up rather than an
approximation the account table quietly carries.

**R3 — own-realised-performance feedback.** `UC-ALPHA-ADAPTIVE-001` remains deferred on its original
basis: PRD §5.4 routes it to §6.6 account history and §5.7 model state, and `account/history.py` is
a zero-byte file. That deferral is unchanged and is narrower than it was: member-level
weighting from *recorded member outcomes* is delivered here for the decision-time surface — weights
and account state — while the realised performance series it would ultimately prefer waits on R4.

## Validation

- `uv run pytest -q` — 353 passed, from 322 at the milestone start.
- `uv run ruff check` and `ruff format --check` clean; package imports.
- `uv run python showcases/show_006_ensemble_netting/run.py` — three real runs, reversal published
  over 16 occurrences with `state_path` moved, momentum over 11 with `state_path` constant, both
  subscribed by dataset id, 11 crossing occurrences with a maximum ticker offset of `0.04`, 9
  rebalances, 14 whole-share fills on the KRX profile, no surviving short, the fill journal
  replaying to the committed Account exactly at `960679501.45`, and identical SHA-256 manifests
  across two clean runs.
- `uv run python showcases/show_005_enhanced_index/run.py` — still green, now also reporting 84
  recorded signal rows and asserting the default records are present.
