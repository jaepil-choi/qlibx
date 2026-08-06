# 020 Authoritative post-commit failure evidence

## Why

`DailyExecutionFlow` reported every flow-generated failure as `CommitStatus.NONE`, including a
memory or artifact failure after a FillBatch had already changed the Account. Operators could
therefore interpret a mutated run as safe to restart before execution even though the Account
version, cash, and positions had advanced.

## Outcome

The flow now records each authoritative Account or Strategy Memory commit with its callback event,
authority, idempotency identity, and resulting version. A later failure in the same callback is
automatically marked `COMMITTED` and carries those exact records. Its retry precondition requires
resuming at or after the committed identities instead of replaying them.

Artifact publication failures are translated to a `daily_flow.run` error. This prevents an
artifact-backend error with `NONE` from hiding an Account or Memory commit that happened earlier in
the callback. The bounded original publication errors remain in context for diagnosis.

## Responsibility and flow

Flow remains the only caller of Account and Memory commit APIs, so it is the reliable place to
observe commit boundaries. Call sites do not choose their own `CommitStatus`; they record a
successful authority commit once, and `_fail` derives status from that durable event-local record.
Pre-commit validation failures continue to report `NONE`.

## Alternatives and trade-offs

Passing a boolean or status argument to individual failure calls was rejected because a new
post-commit path could omit it and recreate the defect. Using the current Account version alone was
also rejected because it cannot distinguish a commit made by the current callback from state that
already existed before the callback. Event-local commit records make that distinction explicit.

The flow error wraps artifact publication errors instead of returning them as the sole top-level
failure. This adds one translation layer but preserves both the correct flow commit semantics and
the original backend diagnostics.

## Validation

- Daily execution acceptance: `uv run pytest tests/acceptance/test_execution_scenarios.py -p no:cacheprovider --basetemp=<task path> -q`
  -> 5 passed.
- Full suite: `uv run pytest -p no:cacheprovider --basetemp=<task path> -q` -> 83 passed.
- Ruff on `src/qlibx/flow/daily.py` and the execution acceptance test -> passed.
- `git diff --check` -> passed.

The regression injects an execution-result publication failure after a real-DW Fill commit and
verifies `COMMITTED`, Account version 1, the committed FillBatch event identity, and the retained
backend error.

## Remaining limitations

This change reports commit truth for the in-process daily flow. Durable crash recovery between the
authority commit and evidence publication remains part of the broader checkpoint/recovery gap; the
new error evidence makes that boundary explicit but does not add a persistent transaction across
Account and artifact storage.
