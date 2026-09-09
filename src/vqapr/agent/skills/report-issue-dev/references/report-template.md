# The report skeleton

Copy this whole file into your new `report-YYYY-MM-DD-<slug>.md` and fill it. Every heading is
required. If a section has nothing in it, write why rather than deleting it — "could not
reproduce" and "not attempted" are useful answers; a missing section is not.

```markdown
# <one sentence that states the problem, not the area>

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` (or `PyPI`) |
| reported | 2026-09-09 |
| reporter | `kaist-thesis/vqapr-scenario-testbed`, agent session |
| python / OS | 3.12.8 / Windows 11 |

## What I was doing

<The scenario, in two or three sentences. Why this command, at this point, with this data. A
maintainer who has never seen this project must be able to place the failure in a task.>

## What I expected

<And where the expectation came from — name it: the SKILL.md line, the `--help` text, the
docstring, the envelope's own `fix`. An expectation with no source is an opinion.>

## What happened

<The exact command, then the entire JSON line unedited.>

    $ uv run vqapr check residual-run
    {"correlation_id": null, "ok": false, "stage": "...", "failures": [ ... ]}

## Reproduction

<The shortest sequence that shows it, from a state a maintainer can reach. Say if it needs data
that is not in this project, and whether it reproduced every time or once in N.>

1. `uv run vqapr new sample --out ./repro`
2. `uv run vqapr register ./repro/sample.yaml`
3. `uv run vqapr check sample-run`  <- fails here

Reproduced 3 of 3 attempts.

## Impact

<Blocked, or worked around. If worked around, what the workaround was and what it cost — in time,
and in correctness if the workaround changes a result. If a number is wrong, say which number and
by how much.>

## What would have prevented it

<One or two lines. A different message, a documented value, a check earlier in the pipeline. This
is a suggestion about the surface, not a diagnosis of the code — do not guess at the cause.>
```

## A filled example

The point of the example is the level of detail, not the subject.

```markdown
# `check` accepts a run whose venue holds no clock, and `run` then fails at the first session

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-onboarding-testbed` |
| python / OS | 3.12.8 / Windows 11 |

## What I was doing

Registering a KRX venue from my own fill table for the enhanced-index scenario, then declaring a
single-strategy run over it. `check` is the step the run-backtest skill names as the gate before
`run`, so I treated it as the point where a bad declaration gets caught.

## What I expected

`run-backtest/SKILL.md` says "`check` makes every judgment `run` makes, before anything is
written". I expected a venue missing its `trade_at` column to be refused by `check`.

## What happened

    $ uv run vqapr check enhanced-run
    {"ok": true, "stage": "check", "mutation": false, ...}

    $ uv run vqapr run enhanced-run
    {"ok": false, "stage": "flow.session", "failures": [{"status": 500, "code":
    "unhandled", "cause": {"type": "KeyError", "message": "trade_at", "where":
    "vqapr/exchange/execution_table.py:212"}, "fix": null, ...}]}

## Reproduction

1. Register a fill table whose parquet has `at` where the docs use `trade_at`.
2. `uv run vqapr register ./venue.yaml` — succeeds.
3. `uv run vqapr check enhanced-run` — succeeds. **This is the defect.**
4. `uv run vqapr run enhanced-run` — status 500 at the first session.

Reproduced 2 of 2 attempts, on a fresh workspace both times.

## Impact

Not blocked — renaming the column to `trade_at` fixed it, about 40 minutes to find because the
500 named a file inside the package and `check` had said the declaration was sound. The cost is
that `check` cannot be trusted as the gate the skill says it is.

## What would have prevented it

`check` refusing the registration with the column name, or `register` refusing it earlier — the
schema is knowable at registration, and a 500 at session one is the latest possible place to
learn it.
```

## Rules that the skeleton is enforcing

- **The version is a fact, not a recollection.** Read it from `vqapr skill list` or `uv pip show
  vqapr` at the moment you file.
- **The envelope goes in whole.** Truncating it removes exactly the fields a maintainer searches.
- **Name the source of the expectation.** "I expected X" is unactionable; "SKILL.md line 41 says
  X" is a contract to check.
- **Separate observation from diagnosis.** The last section suggests; it does not conclude. What
  the package did wrong internally is not visible from here and guessing at it has misdirected
  real fixes before.
- **Say how often it reproduced.** "Once, could not repeat" is a legitimate and useful report.
