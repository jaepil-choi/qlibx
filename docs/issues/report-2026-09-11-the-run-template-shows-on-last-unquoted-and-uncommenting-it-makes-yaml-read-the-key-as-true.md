# The run template shows `on: last` unquoted, and uncommenting it makes YAML read the key as `True`

**Status: RECEIVED 2026-09-11 (접수) — confirmed against `develop`: `src/vqapr/cli/new.py` writes `# on: last` unquoted (record `253` added it), and PyYAML reads the bare key `on` as `True`. Being fixed on `develop`.**

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `git+https://github.com/jaepil-choi/vqapr@b8b47e6c181e65d76e8a2589fd012002dff7c8d2` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-demo-testbed`, recorded Claude Code session (Opus 5) in a fresh project |
| python / OS | 3.12.13 / Windows 11 Enterprise 10.0.26200 |

## What I was doing

Recording the "write a strategy" demo: monthly rebalancing on the last trading day of each month.
The agent generated a run declaration with `vqapr new run`, set `agenda.every: 1M`, and uncommented
the template's own `on: last` line.

## What I expected

That uncommenting a line from the template `vqapr new run` emits yields a valid declaration. The
template, line 23:

    agenda:                          # the strategy clock: a day filter and a within-day rule
      every: 1d                      # 1d | 2d | 1w | 1M select trading days and pair with `at`;
      # on: last                     # 1w | 1M only: the LAST trading day of each week or month

## What happened

YAML 1.1 (PyYAML) reads the bare key `on` as the boolean `True`. Registration refused with a
message about the whole run shape, and the only pointer to the cause was pydantic's
`agenda.1 Keys should be strings [input_value=True, input_type=bool]`. The agent fixed it by
quoting the key (`"on": last`).

The envelope below is as the agent captured it. Its command piped the output through
`head -c 1500`, so the line is truncated. Nothing else is edited.

    $ uv run vqapr register runs/mom12_top30.yaml
    {"correlation_id": "8f6c595afdd74a5988674d39747be10f", "error": "VqaprError: register: 1 failure(s)\n  [400 declaration.run_invalid] a run declares writes, and one strategy (with exchange, execution {dataset, trade_price, fill?} and initial_account) or one datamodel (with agenda.days_from), plus instruments, start, end, timezone and agenda (every, at or from/to), each in the shape `vqapr new run` emits", "failures": [{"cause": {"message": "1 validation error for RunDefinition\nagenda.1\n  Keys should be strings [type=invalid_key, input_value=True, input_type=bool]\n    For further information visit https://errors.pydantic.dev/2.13/v/invalid_key", "origin": null, "traceback": "Traceback (most recent call last):\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\vqapr\\project\\registration.py\", line 906, in _apply\n    definition = RunDefinition.model_validate({\"run_id\": str(run_id), **declared_run})\n                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\pydantic\\main.py\", line 732, in model_validate\n    return cls.__pydantic_validator__.validate_python(\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\npydantic_core._pydantic_core.ValidationError: 1 validation error for RunDefinition\nagenda.1\n  Keys should be strings [type=invalid_key, input_value=True, input_type=bool]\n    For further information visit https://errors.pydantic.dev/2.13/v/invalid_key\n", "type"  [truncated here by the capturing command's head -c 1500]

## Reproduction

1. `uv run vqapr new run --out run.yaml`.
2. Fill it in, set `every: 1M`, and uncomment `# on: last` as written.
3. `uv run vqapr register run.yaml` → 400 `declaration.run_invalid`, `agenda.1 Keys should be strings`.
4. Change the line to `"on": last` → accepted.

Happened once in a recorded session. That the template line reads `# on: last` unquoted was
re-checked with `vqapr new run` on the same version.

## Impact

Worked around by the agent within a minute. But the `requirement` text restates the entire run
schema and names neither `on` nor YAML booleans, so the only clue is a pydantic message with an
index (`agenda.1`) instead of a key name. A person editing YAML by hand would not connect
`input_value=True` to the word `on`.

## What would have prevented it

- Write the template line as `# "on": last`, or rename the key to something YAML does not coerce
  (`on` / `off` / `yes` / `no` / `y` / `n` are YAML 1.1 booleans).
- Or detect a boolean key under `agenda` and refuse with a message that names `on` and says to quote it.
