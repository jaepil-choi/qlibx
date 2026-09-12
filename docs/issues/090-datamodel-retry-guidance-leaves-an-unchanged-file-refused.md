# 090 — The documented way to retry a datamodel run leaves an unchanged file refused, and the refusal calls it a strategy

**Status: CLOSED 2026-09-10 -- record `216`.** The refusal is `record.exists`, 409, stage `record`,
naming the model's kind ("a datamodel record is written once per run and fingerprint") and
`vqapr run <id> --force`, with no traceback; the `--force` help says both kinds and the dataset.
`running-a-datamodel.md` "Retrying" says the retry is `--force`, names both refusals with their
current codes, and demotes `rm dataset` to "drop an output"; two other skill files that named
`datamodel.output_registered` say `run.output_registered`. The state `rm dataset` leaves behind is
what `091`/record `217` makes visible.

Filed as `report-2026-09-09-datamodel-retry-guidance-leaves-an-unchanged-file-refused.md`; numbered
on triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Driving a parameter sweep over ~190 alpha DataModels: for each candidate, register the component,
run it, measure its output dataset, edit one module-level constant, run again. Automating that
needs a dependable "run this alpha again" step.

## What I expected

`references/running-a-datamodel.md` in the `make-datamodel` skill, section "Retrying", says:

> Running the same run again is refused while its output dataset is registered
> (`datamodel.output_registered`, 409).
>
> ```
> vqapr rm dataset <id>
> ```
>
> withdraws the registration **and deletes the files** under `.vqapr/materialized/<id>/`. That is
> the way to retry a datamodel run, or to drop a throw-away output.

I read that as: `rm dataset` then `run` is *the* retry procedure for a datamodel run.

## What happened

It is the retry procedure only when the component's file has changed. With the file unchanged,
`rm dataset` succeeds — deleting the output — and then `run` is refused by a **different** failure
that the "Retrying" section never mentions, leaving the alpha with no dataset at all:

    $ uv run --no-sync vqapr rm dataset alpha-season-004-values
    {"deleted": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr\\materialized\\alpha-season-004-values", "identifier": "alpha-season-004-values", "kind": "dataset", "ok": true, "removed": true, "stage": "workspace.remove", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}

    $ uv run --no-sync vqapr run alpha-season-004
    {"correlation_id": null, "error": "InputError: a strategy record is written once per run and fingerprint", "failures": [{"cause": {"message": "run record 'alpha-season-004/alpha-season-004@147b999d' already exists at D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr\\runs\\alpha-season-004\\datamodels\\alpha-season-004@147b999d", "origin": null, "traceback": "Traceback (most recent call last):\n  File \"...\\vqapr\\record\\writer.py\", line 318, in _open\n    (directory / TABLES_DIRECTORY).mkdir(parents=True)\n  File \"...\\Lib\\pathlib.py\", line 1311, in mkdir\n    os.mkdir(self, mode)\nFileExistsError: [WinError 183] <the OS message, localised>: '...\\\\.vqapr\\\\runs\\\\alpha-season-004\\\\datamodels\\\\alpha-season-004@147b999d\\\\tables'\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"...\\vqapr\\cli\\run.py\", line 224, in run\n    outcome = execute_run(\n  File \"...\\vqapr\\flow\\orchestration.py\", line 240, in run\n    return _run_datamodels(\n  File \"...\\vqapr\\flow\\orchestration.py\", line 374, in _run_datamodels\n    result, record = _run_datamodel(\n  File \"...\\vqapr\\flow\\orchestration.py\", line 472, in _run_datamodel\n    opened_writer.open(replace=replace_record)\n  File \"...\\vqapr\\record\\writer.py\", line 268, in open\n    self._open(directory, replace=replace)\n  File \"...\\vqapr\\record\\writer.py\", line 333, in _open\n    raise RunRecordExists(self.label, directory) from taken\nvqapr.record.writer.RunRecordExists: run record 'alpha-season-004/alpha-season-004@147b999d' already exists at ...\n", "type": "RunRecordExists", "where": null}, "code": "argument.value_invalid", "example_total": 0, "examples": [], "fix": "edit the strategy (a new fingerprint records beside the old one), or replace this record deliberately: vqapr run alpha-season-004 --force", "observed": "'alpha-season-004/alpha-season-004@147b999d' already has a record at D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr\\runs\\alpha-season-004\\datamodels\\alpha-season-004@147b999d", "requirement": "a strategy record is written once per run and fingerprint", "source": {"file": null, "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": "edit the strategy (a new fingerprint records beside the old one), or replace this record deliberately: vqapr run alpha-season-004 --force", "stage": "usage", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}

(The traceback field is reproduced with absolute paths and the localised Windows message elided for
width; everything else is verbatim.)

Three observations:

- It is **status 400 `argument.value_invalid`**, not the **409 `datamodel.output_registered`** the
  section documents. A caller that handles the documented code does not catch this one.
- Every noun says **strategy** for a datamodel run: `error` is "a **strategy** record is written
  once per run and fingerprint", `fix` and `retry_precondition` say "edit the **strategy**", and
  `vqapr run --help` describes `--force` as "replace a **strategy** record". This run declares
  `datamodels:` and no `strategies:`, and its record lives under `runs/<id>/datamodels/`. I spent
  time looking for a strategy-subsystem mistake I had not made.
- A full Python traceback ending in `FileExistsError` rides along on what is a routine 400 for
  user input.

**The `fix` itself is correct and actionable** once read as applying to datamodels: `--force`
exists and is documented in `vqapr run --help`. This report is not that the fix does not work.

## Reproduction

Reproduced every time (3 of 3):

1. Register a datamodel component and a run for it; `vqapr run <run-id>` (succeeds).
2. `vqapr rm dataset <output-id>` (succeeds, deletes the parquet).
3. `vqapr run <run-id>` with the component file **unchanged** — refused, 400, and no output exists.

## Impact

Worked around, after a wrong turn that cost real time and set up a silent correctness bug.

Because the "Retrying" section presents `rm dataset` as the whole procedure, I built my sweep as
"rm dataset, then run" and hit this on the first re-measurement. Not having read `--force` at that
point, I worked around it by parsing the record ref out of the refusal and calling
`vqapr rm datamodel <run-id>/<id>@<fp8>` before re-running. That works, but it is a heavier
intervention than `--force` and it destroys a record the user may have wanted to keep — in a
tuning workflow those records *are* the history.

The more expensive consequence was the state in between. After step 2 the alpha has no output; if
a caller then abandons the retry, the workspace holds a component and a record with no dataset. My
sweep restored each file to its best-measured version and, seeing the dataset directory still
present for other alphas, did not re-run — so five of eight pooled alphas ended up with a
materialized dataset produced by a *different* version than the file on disk. That was my bug, but
this ordering is what set it up; see the companion report on a materialized dataset not recording
its producing fingerprint.

## What would have prevented it

The "Retrying" section naming both refusals — the 409 while the dataset is still registered, and
the 400 when a record already exists for an unchanged fingerprint — and pointing at `--force` for
the second. And saying "datamodel" rather than "strategy" in `error`, `requirement`, `fix`,
`retry_precondition` and the `--force` help text when the run declares `datamodels:`.
