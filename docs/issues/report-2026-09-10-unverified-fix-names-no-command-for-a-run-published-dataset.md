# `dataset.unverified` tells a run-published dataset to "register again", and no command does that

**Status: CLOSED by record `243` (2026-09-10, 0.14.2) — the refusal names the run that published the dataset and `vqapr run <run-id> --force` as the command; a declared dataset's refusal names `vqapr register`; the 0.12.0 migration note carries the run-published line.**

| | |
|---|---|
| vqapr version | `0.13.0` |
| installed from | `../../vqapr/dist/vqapr-0.13.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Migrating a 0.11.0 workspace to 0.13.0. 0.12.0 measures a dataset once, at registration, and a run
that reads a dataset registered before that is refused as `dataset.unverified` (412). The 0.12.0
migration note says what to do:

> **Every registered dataset.** Run `vqapr register <your declaration file>` once more.

I did, for the three declaration files this project has (`datasets.yaml`, `venue_dataset.yaml`,
`ff5_dataset.yaml`); all three registered.

## What I expected

That the next refusal, if any, would name something the same step fixes -- or a step that exists.

## What happened

The next refusal names a dataset that no declaration file declares: the output of a datamodel run,
published through its `writes`. The `fix` tells me to register it:

```
dataset.unverified 412
observed: dataset 'alpha-beta-001-values' was registered before the measurement existed
fix:      register dataset 'alpha-beta-001-values' again
```

`vqapr register` takes a declaration YAML, or a component kind with a `.py`; nothing else:

```
positional arguments:
  declaration   path to the declaration YAML, or the component kind
                (compliance, datamodel, strategy) when registering a .py directly
```

A dataset a run published has no declaration of its own -- the run's `writes:` names it, and the
run is what put it in the workspace. There is no file to hand `register`. The same holds for every
output in the chain: `residual-returns-k200`, the six `factor-<leg>-weights`, the three formation
datasets, the 671 alpha outputs.

The full `check` envelope, verbatim:

```json
{"blocked": [], "checked": ["workspace", "run", "judgments", "preflight"], "failures": [{"cause": {"message": null, "origin": "user", "traceback": null, "type": null, "where": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Scripts\\vqapr.exe\\__main__.py:10 (<module>)"}, "code": "dataset.unverified", "example_total": 0, "examples": [], "fix": "register dataset 'alpha-beta-001-values' again", "observed": "dataset 'alpha-beta-001-values' was registered before the measurement existed", "requirement": "a dataset a run reads must have been measured at registration -- its span, its key and the digest of its bytes -- and this registration carries no such measurement", "source": {"file": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr\\materialized\\alpha-beta-001-values", "key_path": "datasets.alpha-beta-001-values", "line": null}, "status": 412}], "ok": false, "passed": ["workspace", "run", "judgments"], "skipped": [], "stage": "check", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}
```

## What does work

Publishing it again. `vqapr run <producing-run> --force` re-writes the dataset, and the re-written
registration is measured: I re-ran the three runs that read only sources
(`annual-fundamentals`, `momentum-signal`, `kospi-weights`) with `--force`, and then
`firm-characteristics` -- which reads `annual-fundamentals-values` -- ran and published without a
`dataset.unverified`. Row counts were identical to 0.11.0's (2,082 / 26,210 / 1,501,970).

So the fix is real; it is just not the one the envelope names, and not one the migration note
mentions.

## Reproduction

Reproduced on every run-published dataset `check` reached (two, then the whole chain by inference
from the fix's wording):

1. Under 0.11.0, run a datamodel run so it publishes its `writes` dataset.
2. Upgrade to 0.12.0 or later; register the source declarations again.
3. `vqapr check` a run that reads the published dataset -> `dataset.unverified`, fix "register
   dataset '<id>' again".

## Impact

Worked around, and the workaround is the size of the project: every run in the chain runs again,
in dependency order -- formation datasets, six factor legs, the residual model, 671 alpha
datamodels, and 905 gate strategy runs. 0.13.0 makes that far cheaper than it would have been
(native `--jobs` for datamodel runs, one baked cube per batch), and it is still the difference
between "register three files" and "rebuild everything".

The cost of the wording was the half-hour spent establishing that the named fix did not exist
before trying the one that does.

## What would have prevented it

The dataset already knows what published it -- `list datasets` shows `produced_by` and
`produced_by_record`. The refusal could use that: *"dataset 'alpha-beta-001-values' was published
by run 'alpha-beta-001' before the measurement existed; publish it again with
`vqapr run alpha-beta-001 --force`"*. And the 0.12.0 migration note could add one line for
run-published datasets beside the one for declared ones.
