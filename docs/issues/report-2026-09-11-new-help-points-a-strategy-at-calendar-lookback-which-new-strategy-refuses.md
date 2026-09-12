# `vqapr new --help` tells a strategy author to use `--calendar-lookback`, and `new strategy` refuses it — 3 of 3 agents hit it

**Status: CLOSED 2026-09-11 — record `251`** (fixed on the owner's instruction, unnumbered). `new strategy --calendar-lookback DAYS` scaffolds a `CalendarLookback` with the guard that window implies.

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ab-testbed`, runs `B-1` (opus), `B-3` (sonnet), `B-4` (fable), agent sessions; reproduced by the evaluator session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

Scaffolding a 12-month momentum strategy. Its signal needs a calendar window of about 400 days of
prices for every name, and `--lookback` counts rows.

## What I expected

That the flag the help recommends would work for the kind being scaffolded. `vqapr new --help` is
one help page for every kind, and its `--lookback` entry says:

    --lookback LOOKBACK   rows of the table the model reads back -- the same N
                          instants for every name, on a panel-grain dataset. Use
                          --calendar-lookback for a window of N days, or
                          --instants-lookback for each name's own last N
                          reported instants on a rows-grain (vendor, long)
                          dataset

The `--calendar-lookback` entry itself says "scaffold a **datamodel** that reads a CALENDAR window",
but a reader who wants a day window reaches it through the `--lookback` sentence above, which does
not mention the restriction.

## What happened

    $ vqapr new strategy mom --dataset sample-prices --calendar-lookback 400 --out m.py
    {"correlation_id": null, "error": "InputError: --calendar-lookback applies to the datamodel scaffold", "failures": [{"cause": {"message": null, "origin": null, "traceback": null, "type": null, "where": null}, "code": "argument.value_invalid", "example_total": 0, "examples": [], "fix": "scaffold the strategy with --lookback, whose signal counts observations per name, and edit its DatasetInput if you want a calendar window", "observed": "--calendar-lookback given for kind strategy", "requirement": "--calendar-lookback applies to the datamodel scaffold", "source": {"file": null, "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": "scaffold the strategy with --lookback, whose signal counts observations per name, and edit its DatasetInput if you want a calendar window", "stage": "usage", "workspace_root": "C:\\Users\\...\\scratchpad\\repro\\nojobs"}

The same flag on `new datamodel` succeeds. The refusal's `fix` is correct and specific, and all three
agents followed it. So the envelope did its job; what is inconsistent is the help, and the gap in
what the strategy scaffold offers.

## Reproduction

1. `vqapr new sample --out ./s`, then `vqapr register ./s/sample.yaml`
2. `vqapr new strategy mom --dataset sample-prices --calendar-lookback 400 --out m.py` — the
   refusal above.
3. `vqapr new datamodel momdm --dataset sample-prices --calendar-lookback 400 --out mdm.py` —
   succeeds.

Reproduced 1 of 1. In the A/B experiment, all three B agents tried it first (3 of 3), independently.

## Impact

Worked around every time, at one retry plus a hand edit of the scaffolded `DatasetInput` to
`CalendarLookback`. Small per person, but it is the first command most strategy authors run, and
the help sent every one of them to it.

## What would have prevented it

Either `new strategy` accepting `--calendar-lookback`, since the refusal already says the edit is
just the `DatasetInput`, or the `--lookback` help saying the calendar option is for datamodels, with
the strategy route spelled out.

Envelopes saved whole at
`kwam-enhanced-index/vqapr-ff3-testbed/analysis/repro/new_strategy_calendar_lookback_envelope.json`
and `…/new_datamodel_calendar_lookback_envelope.json`.
