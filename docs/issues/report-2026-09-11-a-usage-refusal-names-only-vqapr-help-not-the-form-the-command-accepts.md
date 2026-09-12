# A usage refusal's `fix` says only "run `vqapr --help`", not the form the command accepts — two agents drew opposite rules from the same refusal

**Status: CLOSED 2026-09-11 — record `250`** (fixed on the owner's instruction, unnumbered). The refusal names the subcommand's usage line and `vqapr <command> --help`, and `observed` carries the refused tokens.

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ab-testbed` (runs `B-1`, `B-3`, `B-4`) and `vqapr-ff3-testbed` (runs `B-1`, `B-2`), agent sessions; reproduced by the evaluator session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

Five fresh agents set up a venue roster (`vqapr new instruments`), and one read back a strategy
record (`vqapr show strategy`). Each passed arguments in a natural but wrong form.

## What I expected

`introduce-vqapr/SKILL.md`: "When `ok` is false, read `fix` first." The accepted forms are written
down, just not where the refusal points:

- `vqapr new --help`: `usage: vqapr new ... [--instruments [INSTRUMENTS ...]] ... {…,instruments,…} [component_id]`,
  so ids go through `--instruments`.
- `vqapr show --help`: `vqapr show strategy <run-id>/<strategy-id>@<fp8>`, and the analyze-result
  and inspect-workspace skills say the same.

## What happened

Both refusals come from argument parsing and carry the same generic `fix`. `observed` is the
program name, not the argument that was refused.

    $ vqapr new instruments A000020 A000030 --out i1.yaml
    {"correlation_id": null, "error": "UsageError: unrecognized arguments: A000030", "failures": [{"cause": {"message": null, "origin": "user", "traceback": null, "type": null, "where": "D:\\chljeffreyz\\DevProjects\\vqapr-ab-runs\\B-1\\.venv\\Scripts\\vqapr.exe\\__main__.py:10 (<module>)"}, "code": "usage.rejected", "example_total": 0, "examples": [], "fix": "run `vqapr --help` to see the arguments this command accepts", "observed": "vqapr", "requirement": "unrecognized arguments: A000030", "source": {"file": null, "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": null, "stage": "usage"}

    $ vqapr show strategy sample-run --strategy sample-reversal-5d
    {"correlation_id": null, "error": "UsageError: unrecognized arguments: --strategy sample-reversal-5d", "failures": [{"cause": {"message": null, "origin": "user", "traceback": null, "type": null, "where": "D:\\chljeffreyz\\DevProjects\\vqapr-ab-runs\\B-1\\.venv\\Scripts\\vqapr.exe\\__main__.py:10 (<module>)"}, "code": "usage.rejected", "example_total": 0, "examples": [], "fix": "run `vqapr --help` to see the arguments this command accepts", "observed": "vqapr", "requirement": "unrecognized arguments: --strategy sample-reversal-5d", "source": {"file": null, "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": null, "stage": "usage"}

`vqapr --help`, where the `fix` points, is the top-level help and does not list `new`'s or
`show`'s arguments.

What the agents concluded:

- momentum `B-4`: "ids must be passed via `--instruments`". This is correct.
- momentum `B-3`: "the `--instruments` flag doesn't apply to the `instruments` scaffold kind". This
  is wrong. The agent bypassed the scaffold and called `vqapr.public.register_instruments` directly.
- FF3 `B-1`: "I wrote the instrument list file directly instead". It never found the accepted form.
- FF3 `B-2`: tried the positional form, then `--instruments`, and continued.
- momentum `B-1`: `show strategy <run> --strategy <id>` was refused, and the agent found the
  `<run>/<strategy>` form by trial.

## Reproduction

1. `vqapr new instruments A000020 A000030 --out i1.yaml` fails as above. With
   `vqapr new instruments --instruments A000020 A000030 --out i2.yaml`, it succeeds.
2. On the shipped sample: `vqapr show strategy sample-run --strategy sample-reversal-5d` fails as
   above. With `vqapr show strategy sample-run/sample-reversal-5d`, it succeeds.

Reproduced 1 of 1 each. The agents above hit it independently in five sessions.

## Impact

Worked around every time, at a few minutes each. The costlier outcome is that two agents read
the same refusal and wrote down opposite rules, and one of them skipped the scaffold for a direct
API call.

## What would have prevented it

A usage refusal whose `fix` names the subcommand's own usage line (for example,
`vqapr new instruments --instruments ID [ID ...] --out PATH`), or at least `vqapr new --help`
rather than `vqapr --help`, and whose `observed` carries the arguments that were refused.
