# Correcting a registration

## The ordinary loop: register the same id again

A registration is an identity — one id means one declaration — and editing something you already
registered is the same command twice:

```bash
vqapr register prices.yaml     # again, with the file edited
```

It replaces the registration in place, with no flag — there is no `register --force`. The two
`--force` flags that do exist belong elsewhere: `vqapr run --force` replaces a run *record*, and
`vqapr skill install --force` overwrites edited skill files.

The success payload then carries `replaced: {fingerprint: <the old one>}`, and says nothing about
it when the id was new or the bytes unchanged. The id stays, whatever names it keeps working, and
the next run's record carries a new `source_digest`.

## That digest is a receipt, not a gate

It records what ran. Nothing re-checks it afterwards. Two runs of edited code carry two different
digests, which is exactly what makes an edit visible in the record — and a run that already pinned
the old fingerprint is unaffected, because its record testifies to what it used.

## The exception: a `runs:` declaration

A run definition is the provenance of a result, so re-registering the same `run_id` with a changed
body is refused (`run.registered`, 409). During setup, withdraw it first:

```bash
vqapr rm run-definition <run-id>
vqapr register runs.yaml
```

Its records, if any, stay readable.

## Withdrawing

```bash
vqapr rm <kind> <id>
```

Refused while a registered run still names it — and the refusal names which run. A dataset
registered from the user's own path is withdrawn without touching their file.

`vqapr rm dataset <id>` on a **materialized** dataset also deletes the files under
`.vqapr/materialized/<id>/`. That is the way to retry a DataModel run or drop a throw-away output.
It refuses while a registered run takes its sessions from that dataset (`sessions_from`), naming
the run.

## When it is genuinely a different thing

Give it its own id. One id never means two things.

The judgement is the same one the strategy-file rule makes: re-registering an edited file reads as
*tuning* the same thing, and a reader of the record sees it that way. Another arm of a methodology,
a different signal, the same shape with one constant changed — those are a new id.

## Resetting a disposable workspace

If this is a first-run workspace with no result worth preserving:

1. Keep the authored YAML and component files.
2. Obtain the user's approval for a destructive reset.
3. Remove only the project-local `.vqapr/` workspace state.
4. Register the corrected declarations from scratch.

**Never delete source data or authored declarations as part of that reset.**
