# The CLI protocol declares its encoding instead of inheriting the caller's

Specifies PRD 5.1.

## Why this change exists

`cli._print` emitted `json.dumps(..., ensure_ascii=False)` through `print`, which encodes with
the locale codec. The encoding of an agent-facing JSON protocol was therefore a property of the
machine that ran the command, not of the protocol:

- On a UTF-8 host the response was UTF-8. On a Korean Windows host it was cp949, and on a
  Western one cp1252 — the same command, three different byte streams for the same characters.
- Any character outside that codepage raised `UnicodeEncodeError` from inside the CLI while it
  was reporting a perfectly valid result.

The failure was found through a symptom that looked like a test defect. `tmp_path` on this
machine is `C:/Users/최재필/AppData/Local/Temp/...`, so the acceptance journey's very first
`project init` echoed a Hangul path back as JSON. The test decoded it with
`subprocess.run(text=True)`, which uses `locale.getencoding()` (cp949) and — unlike the child —
ignores `PYTHONIOENCODING`. The reader thread died with `UnicodeDecodeError`, `completed.stdout`
became `None`, and the failure surfaced as `json.loads(None)`.

That asymmetry is why the obvious one-line fix was wrong. Adding `encoding="utf-8"` to the test
would have made it pass on a machine that exports `PYTHONIOENCODING=utf-8` and fail on one that
does not, because the child's bytes moved with the environment either way. The environment was
never supposed to be part of the contract.

## What changed

`cli._declare_output_encoding()` runs at the top of `main()` and pins both streams:

```python
for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "backslashreplace")):
```

stdout is strict, because a byte sequence the agent cannot decode is a broken response and
should fail loudly rather than be silently repaired. stderr degrades instead, because it is a
diagnostic channel and must not fail while reporting a failure.

It sits in `main()` rather than in `__main__.py` so that both entry points — `python -m qlibx`
and the installed `qlibx` console script, which calls `cli:main` directly — are covered by one
statement.

`getattr(stream, "reconfigure", None)` guards the case where stdout has been replaced by an
object without it (pytest's capture, a caller's redirect). Those callers hold `str`, so the
byte encoding is not theirs to decide.

## Trade-offs

- **A legacy console with a non-UTF-8 codepage now shows mojibake for non-ASCII text** where it
  previously showed correct characters. It is the right trade for this surface: the consumer of
  `_print` is an agent parsing JSON, and correctness for that consumer cannot depend on the
  reader's codepage. The alternative considered — `ensure_ascii=True`, which is safe under every
  codec — was rejected because it renders every Korean string in the documentation and error
  commands as `\uXXXX` for the human reading over the agent's shoulder.
- **Warnings written before `main()` runs are still locale-encoded.** An interpreter or import
  warning is emitted before any qlibx code executes, so a stderr stream can carry two encodings.
  This is why the acceptance helper decodes stderr with `errors="replace"` and asserts only on
  stdout.

## Invariants

- `test_cli_json_is_utf8_whatever_the_callers_locale_says` — runs the CLI as a subprocess with
  `PYTHONIOENCODING` and `PYTHONUTF8` cleared from the environment, in a project directory named
  `한글-프로젝트`, and decodes stdout as UTF-8 strictly. Clearing the variables is the point of
  the test: it reproduces what a plain shell gives the child, rather than what this developer's
  shell happens to export.

The acceptance helper `_qlibx` now captures bytes and decodes each stream itself — stdout
strictly as UTF-8, stderr leniently — instead of using `text=True`, whose locale decoding was
what turned a readable response into `None`.

## Validation

- `uv run pytest` under PowerShell (the shell where this failed): `145 passed`. This is the
  first fully green run in that environment; every prior implementation record in this session
  recorded `1 failed` here and attributed it to a pre-existing cp949 defect.
- `uv run pytest` under bash: `145 passed`. The two environments differ in whether
  `PYTHONIOENCODING` is exported, which is what made the old failure look intermittent.
- `uv run ruff check .` — clean.
- Mutation check: with `src/qlibx/cli.py` stashed and the tests kept, the new test fails. The
  guard is on the fix, not on the environment that happens to run it.

## Still open

`uv run ruff format --check .` reports `docs/qlibx-architecture.md` as needing reformatting — an
aligned comment column inside a Python code block, present since `fd234c4` and untouched here.
Reformatting it destroys the alignment the author chose, so it is left for a decision rather
than silently changed.
