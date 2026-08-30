# 023 — A registered component's source can be edited underneath its digest

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-009**,
`slowed` — *"the finding with the largest gap between what the documentation promises and what the
package does, and the promise is about provenance."*
**Touches:** the installed skill (two paragraphs quoted below), `src/vqapr/cli/check.py` preflight.

## Read `docs/issues/009` before deciding anything here

009 removed the two component-fingerprint refusals on purpose. Its Decision 2 is titled *"the
component fingerprint stops refusing"*, and its argument is that editing a registered component is
the ordinary development loop, that the two refusals pointed at each other in a circle, and that
**provenance does not need the gate because the receipt already exists**. It was closed 2026-08-28
by `docs/implementations/064-a-fingerprint-stops-refusing-and-starts-reporting.md`.

**So the behaviour this journey found is the behaviour 009 asked for.** What this file reports is
that the documentation still describes the world before 009, and that a reader who believes it draws
a false conclusion about a run record.

## What the skill still promises

> Registrations are immutable identities, not editable configuration rows. Re-registering changed
> content under the same id is refused because an old run may depend on the original declaration.

and, of the run spec:

> The spec names already-registered components by id; it does not redeclare them. Preflight refuses
> any drift between the spec and what is registered.

The reporter had planned the recovery the skill prescribes — register the correction under a new id
— before trying it.

## What happens

Two corrections to an already-registered strategy (`invested` 2 -> 1, then adding `diagnostics()`)
were silently picked up and run. So the reporter tested it deliberately: appended one junk line to
`declarations/ff3_monthly.py`, a component registered and already used by a completed run, and
re-ran `check`:

```json
{"blocked": [], "checked": ["spec","workspace","judgments","declaration","preflight"],
 "ok": true, "passed": ["spec","workspace","judgments","declaration","preflight"],
 "stage": "run.check"}
```

Five phases, eight judgments, `ok:true`, and nothing in the report mentions that the source changed.

## The part that is not settled by 009

What IS protected is the **declaration document** — the YAML naming id, path and object_name. What
is not protected is the file that path points at, which is where all the behaviour lives.

The run record does fingerprint it: `vqapr show run` reports a `source_digest`. So the framework
computes the digest, stores it, and never compares it against the file again. The consequence the
reporter names:

> run `ff3-2019-2026` sits on disk with a `source_digest` for a file whose contents I can change at
> will, and `vqapr show run` will keep reporting that run's numbers beside a digest that no longer
> describes anything reachable. **A reader cannot tell.**

009's answer to this is that the digest is a receipt: two runs of edited code already carry two
different digests, and that is stronger provenance than a gate. That answer holds *for two runs*. It
does not cover the single-run case a reader is actually in — one digest on screen, and no way to ask
whether the file it names still hashes to it.

## What closes it

**Docs, at minimum, and it is not optional.** The two skill paragraphs above claim more than the
package delivers and should be narrowed: registration replaces in place (009/064), and preflight
refuses drift between the spec and what is registered — *the declaration*, not the source it points
at.

**Then decide whether a reader gets a way to ask.** 009 forbids re-introducing a gate, and this file
does not propose one. What it proposes is a *statement*: something in `show run` that reports
whether the source at the registered path still matches the digest that run recorded — `matches`,
`differs`, or `absent`. That is a receipt being read back, which is the thing 009 argued for, and it
is the only way the single-run case becomes legible.

**Do not replace this with a warning that is really a gate.** 009's "What not to do" applies here
verbatim.
