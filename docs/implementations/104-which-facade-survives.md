# 104 — Which facade survives

**Closes:** Step 0 of the approved structural plan
(`.gjc/.../plans/ralplan/01a0527d-3021-7671-b998-e928688f75ad/pending-approval.md`).
**Branch:** `step-00-which-facade-survives`.
**Decision only. No source file changes.**

## The decision

**The shipped `vqapr.public` survives and is emptied of orchestration. `project.py` stays frozen and
dies under `G008`.**

`docs/refactoring/2026-08-31-vqapr-structural-refactoring.md` §2 draws the opposite target —
*"`public.py` is gone, `project.py` is the sole facade"*. That target is unreachable without
breaching the ruling in `docs/design/agent-first-surface.md`, which is canonical. This record settles
which of the two governs, so that no later step has to decide it mid-flight.

## Why: five measurements, each checked at `develop@61cb29e6`

**1. The tracer table already answered this.** `docs/design/agent-first-surface.md:240-241` measures a
complete CLI journey — `new` · `register` · `check` · `run` · `show`, all kinds, two runs completing
`ok:true` — against the module set:

| module | executable lines | ran in the CLI journey | ran in the test suite |
|---|---:|---:|---:|
| `vqapr/project.py` | 619 | **0** | 464 |
| `vqapr/simulation.py` | 327 | **0** | 283 |

The proposed destination executes **zero lines** when the product runs. It is exercised only by the
tests written for it.

**2. `project.py` has exactly one importer in `src/`.** Verified:

```
$ grep -rn "from vqapr.project\|from vqapr import project\|import vqapr.project" --include=*.py src/ | grep -v "^src/vqapr/project.py"
src/vqapr/__init__.py:38:    from vqapr.project import open as _open
```

One caller, `vqapr.open()`, which no shipped command reaches.

**3. `public.py` is on every shipped path.** Verified:

```
src/vqapr/cli/check.py:45      from vqapr.public import Workspace, preflight_run
src/vqapr/cli/register.py:66   from vqapr.public import (
src/vqapr/cli/run.py:36        from vqapr.public import (
src/vqapr/cli/run.py:48        from vqapr.public import run as execute_run
src/vqapr/cli/run.py:541       from vqapr.public import MaterializationSpec, materialize
src/vqapr/cli/run.py:770       from vqapr.public import roster_report
src/vqapr/cli/run.py:804       from vqapr.public import _registered_roster
```

Three verbs, seven import sites. The last one reaches a **private** name, which is a defect Step 7
must fix rather than inherit.

**4. The freeze is two-sided, and the audit's target breaches both sides.**
`docs/design/agent-first-surface.md:271-275`:

> - **No new callers.** Nothing in `src/` may add an import of `vqapr/project.py`, `vqapr.open`, …
> - **No growth.** Do not extend these modules to serve a new requirement.
> - **No deletion, either.** Removing them is `G008`, and its conditions are below.

Migrating the shipped orchestrator onto `project.py` adds callers **and** grows it. Deleting
`public.py` instead is `G008`, whose two admission gates — the T0 trace/row comparator over the whole
testbed, and explicit owner approval of the breaking release — are both shut.

**5. Six emitted scaffolds name `vqapr.public`.** Verified:

```
src/vqapr/extension/scaffold.py:65    from vqapr.public import DataModel, DataRequirement, {lookback_class}
src/vqapr/extension/scaffold.py:174   from vqapr.public import (
src/vqapr/cli/new.py:598              from vqapr.public import AcademicExchange, TradeRule
src/vqapr/cli/new.py:613              from vqapr.public import SideCost
src/vqapr/cli/new.py:657              from vqapr.public import KrxExchange, krx_listings
src/vqapr/cli/new.py:774              from vqapr.public import export_roster
```

The ruling requires this (`:276-278`): *"an emitted import is the most-copied artifact in the
package; it must name the surface that will still exist after this ruling."* Emptying `public.py` of
orchestration keeps all six valid. Migrating would invalidate them at once.

## What this costs, stated rather than glossed

- **The audit's §2 diagram is wrong** and carries an erratum, appended by this step. The audit is
  **not** in `.agent/project.yaml:canonical_documents` — that set is `docs/vqapr-prd.md`,
  `docs/design/agent-first-surface.md`, `gjc-handoff/README.md` — so its correction is an erratum
  rather than an amendment, and **no canonical document changes and no owner approval is required**
  for this ruling.
- **`public.py` keeps a name that reads like a re-export module while it is the entry point.** That
  is true today and stays true until Step 7 makes the name honest. Step 7's acceptance is exactly
  that: 775 lines down to under 250, `__all__` unchanged.
- **The orchestration has to land somewhere real** — `flow/` and `evidence/` — which is Step 7, the
  largest non-`simulation.py` step in the campaign.

## If a later reader wants to overturn this

The document that must change is `docs/design/agent-first-surface.md`, specifically "Which facade
ships" and "What frozen means", and only the **owner** can approve that, on the same standing that
froze the cluster and that gates `G008` ("OWNER APPROVAL"). A planner, architect, critic or executor
cannot. This record is not that approval and does not seek it: it rules on which of two documents
governs, and the canonical one wins.

## Validation

No source file changed, so the suite is unaffected and is not the evidence here. The evidence is
that every citation above was re-derived from the tree at `develop@61cb29e6` rather than copied from
the plan: the tracer table, the single importer, the seven shipped import sites, the freeze text and
the six scaffold sites were each grepped and read before this record was written.
