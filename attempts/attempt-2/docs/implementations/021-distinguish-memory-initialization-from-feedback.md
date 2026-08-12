# 021 Distinguish memory initialization from feedback

## Why

The daily flow required every proposed Strategy Memory value to consume an Account feedback cursor
strictly greater than the current Memory cursor. A new Account and new Memory store both start at
cursor zero, so a Strategy could not initialize state on its first decision even though no prior
feedback exists by definition.

## Outcome

The first Memory commit is allowed when the current snapshot is the untouched version-zero state
and the Strategy consumed Account cursor zero. Later updates still require a strictly newer
feedback cursor. Memory evidence now labels each commit as `INITIALIZATION` or `FEEDBACK_UPDATE`,
and lineage calls the initialization input `initial_actual_state` rather than confirmed feedback.

## Responsibility and flow

Strategy continues to propose a value with the Memory version it read. Flow validates CAS, actual
state access, and the cursor rule before calling `StrategyMemoryStore.commit`. The store remains a
generic CAS authority; the daily flow owns the semantic distinction because it has both Strategy
access lineage and Account feedback context.

## Alternatives and trade-offs

Forbidding first-decision Memory was rejected because neither the PRD nor the public Strategy
contract defines initialization as feedback learning. Silently dropping the proposal was also
rejected because it would hide a requested state transition. Treating every equal cursor as an
initialization was rejected because it would permit repeated belief changes without new evidence.

An invalid post-initialization update still fails the run. This preserves the package rule that an
invalid authoritative state proposal is explicit rather than silently ignored; a separate
proposal-rejection workflow would require a distinct product contract.

## Validation

- Daily execution acceptance: `uv run pytest tests/acceptance/test_execution_scenarios.py -p no:cacheprovider --basetemp=<task path> -q`
  -> 7 passed.
- Full suite: `uv run pytest -p no:cacheprovider --basetemp=<task path> -q` -> 85 passed.
- Ruff on `src/qlibx/flow/daily.py` and the execution acceptance test -> passed.
- `git diff --check` -> passed.

The tests verify both boundaries: initial cursor-zero Memory commits with initialization lineage,
while a second proposal at the same cursor fails and leaves Memory at version one.

## Remaining limitations

Memory initialization is still tied to a Strategy callback and one actual-state access. There is no
separate administrative Memory seeding API, and this change does not define a non-fatal rejected
proposal result type.
