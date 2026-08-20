# 029 — The CLI answers in one shape, and `run` is proven to run

## Why this exists

The `vqapr` CLI had four commands and no test that ran any of them. `test_envelope.py` asserted the
parser *mentions* each command in its help text; mentioning is not running. The whole
`spec.yaml → RunDefinition → preflight_run → run` path was unexecuted, because the testbed and the
showcases both assemble `RunDefinition` in Python and never invoke the CLI.

Walking the surface as a first-time user does exposed two defects, both in the contract
`envelope.py` states in its own docstring: *"성공과 실패가 같은 모양이어야 한다"*, and that an agent
can tell "the framework refused" from "something unexpected happened".

## Defect 1 — argparse left through a door the envelope does not watch

`main()` wrapped the handler in `except Exception`. `parser.parse_args()` raises `SystemExit`, which
is a `BaseException`, so it passed straight through:

```
$ vqapr register dataset prices x.parquet Thing
exit=2, stdout empty          # prose on stderr, nothing to parse
```

An empty stdout with a bare exit code is the one reply an agent cannot read, and it was reachable
from every mistyped command.

`_Parser.error()` now raises `UsageError` instead, and `main()` catches it around `parse_args`.
`--help` and `--version` leave through argparse's `exit()` rather than `error()`, so they keep
their existing behaviour — only failure is rerouted.

`UsageError.family` is `None` on purpose. `FailureFamily` is the closed set of *package* stages
(architecture §8.3) and a rejected command line never reached one; picking a member to fill the
field would make an agent classify it as a stage that did not run. The body carries argparse's own
wording verbatim, because inventing text here would be the second, unversioned authority the CLI
docstring exists to prevent. No traceback and no dump ride along: the body is one line already, and
the evidence is the command line the user typed.

## Defect 2 — `run` checked three of the eight keys it cannot run without

`_REQUIRED` listed `strategy`, `valuation`, `instruments`. But this command always continues into
`preflight_run` (which refuses without `start`/`end`) and then `run` (which refuses without an
exchange, an execution input, and an initial account). So five required keys were unchecked, and
each surfaced from deep inside the framework as `stage: "unhandled"` — telling an agent the
framework broke when the truth was that its spec was incomplete.

`RunDefinition` itself is right to permit those fields to be absent: in-process callers supply them
another way. They are required *at this command*, which is where the check now lives. All five are
named in one reply rather than discovered one exception at a time.

**The check also moved ahead of `Workspace.open`.** It reads only the user's own file, so it costs
nothing to run first — and running it second meant an incomplete spec in an uninitialised directory
reported the missing workspace and said nothing about the spec, sending the user to fix the wrong
file. The test that caught this failed for exactly that reason.

## What the end-to-end test proves

`test_run_executes_a_declared_spec_end_to_end` writes a `spec.yaml`, invokes `main(argv)`, and reads
the envelope:

```
{"stage": "run.complete", "occurrences": 12, "account_version": 7, "ok": true}
```

Both numbers are pinned rather than asserted as `> 0`, which a run that did nothing would also
satisfy. `account_version == 7` is the load-bearing one: the account moved seven times, so callbacks
really were invoked and really committed through the CLI path.

`new` and `register` are driven as the user types them, and the test asserts they compose —
`new` emits the `object_name` that `register` requires, so the user never opens the generated file.

## Trade-offs

- **Datasets, sources, agendas, execution inputs and configs are registered through the library in
  the test fixture**, because the CLI has no command that registers them. `register` accepts
  `datamodel|strategy` while `list` reads eight kinds. That asymmetry means a user cannot reach a
  runnable workspace through the CLI alone; it is recorded as a finding rather than papered over,
  because closing it is a new surface, not a fix.
- **`UsageError` lives in `envelope.py`, not `main.py`.** It is part of the envelope contract even
  though the parser is what raises it, and `failure()` returns it early — so there is still exactly
  one place that decides what an envelope looks like.
- **Spec-shaping still raises bare `ValueError`/`TypeError`** for malformed values, so those remain
  `stage: "unhandled"`. Giving spec parsing its own typed stage is a canon decision about the
  failure vocabulary, not a bug fix, and it is left to the owner.

## Validation

```
uv run pytest -q                  584 passed (from 577)
uv run ruff check src/ tests/     clean
G-4 result invariance             64 fields identical
```

Seven tests in `tests/cli/test_commands.py`, the first that execute any CLI command.
