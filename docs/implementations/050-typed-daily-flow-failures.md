# Typed daily-flow failures

## Intent

Daily simulation must reject unsupported physical targets and translate callback/model validation failures into stable operation errors instead of leaking Python exceptions.

## Observable outcome

Long-only targets above one gross fail with `DAILY_TARGET_BUDGET_UNSUPPORTED`; invalid decision construction fails with `DECISION_INTENT_INVALID`; unexpected scheduler callbacks fail with `DAILY_FLOW_CALLBACK_FAILED`. Post-commit failures retain the last authority commit in `commit_status` and error context.

## Responsibilities and flow

The daily flow validates target gross before building a decision, translates Pydantic validation at the decision boundary, and owns the scheduler exception boundary. Existing typed failures pass through unchanged.

## Alternatives and trade-offs

Silently scaling an oversized target was rejected because it changes Strategy intent. Catching all exceptions at the public facade was rejected because it would lose event and authority context.

## Validation

- `uv run python -m pytest tests -q -p no:cacheprovider` -> 247 passed in 114.80s.
- `uv run ruff check .` -> all checks passed.
- `uv run python .agent/tmp/import-smoke.py` -> passed; this ignored script performs `import qlibx` because `cmd.exe` corrupted the requested `python -c` quoting.
- `uv build` -> built `qlibx-0.1.0.tar.gz` and `qlibx-0.1.0-py3-none-any.whl`.
