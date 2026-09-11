# A `vqapr run` batch under `--jobs` writes no run record, so `show run` refuses the runs it reported completed

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.2` (`vqapr skill list` → `package_version`) |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ff3-testbed`, run `B-1` (agent session); reproduced by the evaluator session on the shipped sample |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

Building the Fama-French 3 factors through vqapr: one DataModel run for the June sorts, one for the
market leg, and six StrategyModel runs — one per 2×3 portfolio, each writing its own dataset — on an
academic venue. The six were executed in one command, `vqapr run ff3-port-sl-run … ff3-port-bh-run
--jobs 6`, and each portfolio's `vqapr.account` was then read back to assemble SMB and HML.

## What I expected

That a run the batch reports `status: completed` has the same record a single run has.
`vqapr show --help` offers `vqapr show run <run-id>` for "the configuration every strategy shared",
and `vqapr list runs` lists these runs, so `show run` should open them. The run-backtest skill says a
batch returns "`ok: true` with a `strategies` map where every entry carries `status: completed`",
and the batch did.

## What happened

The batch envelope reports every run completed (`jobs: 2`, both runs `ok: true`). It is 6 KB of
per-strategy timing; the whole line is saved at
`kwam-enhanced-index/vqapr-ff3-testbed/analysis/repro/two_jobs_run_envelope.json`. Its start:

    $ vqapr run sample-run sample-run-2 --jobs 2
    {"jobs": 2, "ok": true, "runs": {"sample-run": {"ok": true, "run_id": "sample-run", "strategies": {"sample-reversal-5d": {"account_version": 729, "contract": {"accepted_intents": 729}, "fills": {"dealt": 1997, "never_filled": [], "orders": 2933, "partial": 0, "reasons": {"no_trade": 936}, "zero_dealt": 936}, "fingerprint": "399e46b214d45746f89a6c9b750b0ed040be5e83d115c789bc67519087fcffc6", "occurrences": 1468, "record": "sample-reversal-5d@399e46b2", "status": "completed", "tables": ["vqapr.account", "vqapr.fill", "vqapr.weight"], ...

`list runs` lists both runs. `show run` says the store holds no run at all:

    $ vqapr show run sample-run-2
    {"correlation_id": null, "error": "InputError: show run requires the id of a run this store holds a record for", "failures": [{"cause": {"message": null, "origin": null, "traceback": null, "type": null, "where": null}, "code": "argument.value_invalid", "example_total": 0, "examples": [], "fix": "run `vqapr list runs` to see what this store holds, then show one of those ids", "observed": "'sample-run-2'; known: (none)", "requirement": "show run requires the id of a run this store holds a record for", "source": {"file": null, "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": "run `vqapr list runs` to see what this store holds, then show one of those ids", "stage": "usage", "workspace_root": "C:\\Users\\...\\scratchpad\\repro\\two_jobs"}

The `fix` sends the reader to `vqapr list runs`, which lists the very id that was just refused.

On disk, `.vqapr/runs/sample-run-2/` holds `strategies/` only. A run executed without `--jobs` holds
`run.json` and `strategies/`.

In the FF3 workspace the same thing happened to all six portfolio runs, and
`vqapr.public.strategy_report(store, "ff3-port-sl-run")` raised `FileNotFoundError`. The two
DataModel runs in that workspace were run one at a time and have `run.json`.

## Reproduction

1. `vqapr new sample --out ./s`
2. In `s/sample.yaml`, copy `runs.sample-run` to `runs.sample-run-2` and set its `writes` to
   `sample-reversal-5d-weights-2`, so the two runs write different datasets. With the same `writes`,
   `--jobs` correctly refuses the batch with `run.batch_writes_collide`.
3. `vqapr register ./s/sample.yaml`
4. `vqapr run sample-run sample-run-2 --jobs 2` — `ok: true`, both completed.
5. `vqapr list runs` — both listed.
6. `vqapr show run sample-run-2` — the refusal above. `sample-run` is refused the same way.

Controls, on fresh copies of the same workspace:

| command | `run.json` written | `show run` |
|---|---|---|
| `vqapr run sample-run sample-run-2 --jobs 2` | neither run | refuses both |
| `vqapr run sample-run sample-run-2` (no `--jobs`) | both | opens both |
| `vqapr run sample-run --jobs 2`, then `vqapr run sample-run-2 --jobs 2` | both | opens both |

The single-run `--jobs 2` envelope carries no `jobs` key, so a batch of one does not seem to use
the pool. Reproduced 1 of 1 on the sample, and seen in two independent FF3 workspaces:

- `vqapr-ff3-runs/B-1`: six portfolio runs under `--jobs 6`, none with `run.json`.
- `vqapr-ff3-runs/B-2`: six portfolio runs (`ff3-s1` … `ff3-b3`) under `--jobs 3`, none with
  `run.json`. That workspace's DataModel run, `ff3-classify-run`, was run on its own and has one.

## Impact

Worked around, with no wrong number found. `read_strategy_table(store, run_id, "vqapr.account",
strategy_ref)` still reads the tables, so the FF3 agent's factors were right; they matched the
published Kimchi factors most closely of any run in the experiment. But after a `--jobs` batch,
`show run` and `strategy_report` refuse every run in it. The agent lost a run of its assembly
script to the `FileNotFoundError` and recorded the gap as a suspected defect.

The pattern the skill recommends for a sweep — several runs in one `--jobs` command — therefore
produces runs that the inspection commands cannot open.

## What would have prevented it

A run in a `--jobs` batch writing the same run-level record a single run writes. Failing that,
`list runs` and `show run` agreeing about which runs the store holds, and the batch envelope saying
when a run's record was not written.

Evidence, left in place: `vqapr-ff3-runs/B-1/.vqapr/runs/` (six portfolio runs without
`run.json`) and `vqapr-ff3-runs/B-1/ff3/run_ports.json` (that batch's envelope).
