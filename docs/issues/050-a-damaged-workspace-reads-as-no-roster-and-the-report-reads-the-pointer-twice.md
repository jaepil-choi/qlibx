# 050 — A damaged workspace reads as "no roster", and the report that describes the roster reads the pointer a second time

**Status when filed:** open. Both halves found 2026-08-31 by the independent review recorded in
`docs/refactoring/2026-08-31-post-step-07-review.md` (R3 and R4), re-verified against
`develop@ec9e6139` on 2026-09-01 before filing. **Filed as one issue because they are one repair**:
the review's own recommendation is that R4 be fixed in the same commit as the first read it removes.
**Touches:** `src/vqapr/flow/roster.py:48` and `:126` (`registered_roster`, `roster_report`).

Sibling to [042](042-a-damaged-roster-pointer-reads-as-no-roster.md), which closed the *pointer*
door. This is the same defect at the *workspace* door, which 042's own closure text names as still
open: *"only `Workspace.open` itself is guarded."*

## Half one — the guard is wider than its reason

```python
try:
    space = Workspace.open(root_path)
except Exception:
    return None
```

`Workspace.open` calls `_read()`, which decodes `.vqapr/workspace.yaml`. A file that is corrupt or
half-written makes it raise a **typed `VqaprError`**. This `except Exception` swallows that and
returns `None`.

**Four lines below it, the module states the principle it is breaking:**

> *"OUTSIDE the guard above, deliberately. [...] 'no roster' and 'a roster whose record is damaged'
> are different states, and only the first is ordinary."*

The guard was written for one of those states — a workspace that is **absent**. The code covers
every state in which a workspace cannot be **read**.

### What it costs

`registry=None` is not a refusal. The run continues, and every fill records `kind: None`.

On an academic venue that is harmless. **On a KRX-shaped venue every name is then charged
identically** — an ETF sleeve at the stock rate — and `cost_by_kind()` collapses to one unlabelled
bucket, so the report that would expose it is the one the gap erases. That is
[007](007-an-undeclared-instrument-is-silently-a-share.md) coming back through a different door.

The window is not theoretical: `.vqapr/workspace.yaml` is rewritten by `vqapr register`, and a
simulation run takes minutes. A register that lands mid-run, a crash mid-write, or a hand edit all
produce it.

## Half two — the report reads the pointer again

`roster_report`'s docstring claims:

> *"The per-category counts come from the roster already loaded for this run rather than from a
> second read, so what is reported is what was bound to the venue, not what the file says now."*

**True of `by_kind` only.** `digest` and `tables` come from a second `space.registered_instruments()`
at `roster.py:135` — the file as it stands now, minutes after `registered_roster` bound the
categories.

### What it costs

A `vqapr register <instruments>.yaml` during a long run makes the frozen record carry the **new**
roster's digest beside fills classified by the **old** one. The `source_digest` / `declared_digest`
pair exists precisely to make that kind of drift visible; here the record manufactures it silently
and reports it as one consistent fact.

## Why one repair

The two halves are the same read. Carrying `digest` and `tables` down from the first read — having
`registered_roster` return them alongside the registry — removes the second read entirely, and the
guard narrowing has to be applied to both call sites anyway. Splitting them means touching
`roster.py`'s two guards twice.

## What would close it

1. **Narrow both guards to workspace absence** (or let `VqaprError` through), which is the treatment
   already applied to the pointer read by 042. `cli/run.py`'s `_roster_envelope` already catches that
   refusal and reports `known: true, stale: true` — the honest answer for a run that read its roster
   and then lost the record of it.
2. **Return the digest and table list from the first read**, so `roster_report` describes the roster
   the run actually used.

**A test that fails on the pre-fix tree first**, for each half. Half one's is a damaged
`workspace.yaml` between preflight and `run()`; half two's is a roster re-registered mid-run, with
the frozen record's digest asserted against the roster the fills were classified by. Without that
ordering the fix is unfalsifiable — this repository has shipped a verified-against-a-double repair
before ([041](041-a-fix-was-verified-against-a-double-the-real-object-does-not-match.md)).
