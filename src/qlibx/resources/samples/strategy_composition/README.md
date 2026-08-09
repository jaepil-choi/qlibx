# qlibx installed Strategy composition

This product-owned example closes the installed workflow for `UC-ALPHA-PATH-001`:

1. two path-dependent Strategies run against distinct simulation Accounts and Strategy Memory;
2. their exact frozen `strategy_result:v2` artifacts are combined without rerunning either
   producer;
3. every source Account/Memory identity and cursor is preserved in transitive lineage;
4. a project-local artifact-only consumer is validated and registered against the exact composed
   result; and
5. that exact registration executes on a separate current Account B.

From an initialized project root run:

```powershell
uv run python examples/qlibx_owned/strategy_composition/run.py .
uv run qlibx strategy list .
```

The source runs end on 2024-01-04, composition and extension validation occur on 2024-01-05, and
Account B decisions begin on 2024-01-08. This ordering is intentional: the example never consumes
a future-created artifact from an earlier decision time.

`consumer_strategy.py` imports only the curated top-level `qlibx` extension surface. The module is
trusted project code, not a security sandbox. The runner refuses to overwrite a modified copy in
the configured extension directory, and qlibx executes only the returned exact registration ID.

The output includes source content hashes before and after composition/execution, producer call
counts, canonical source-state lineage, registration identity, Account B decisions/executions, and
the final Account B state. Source alpha state and downstream execution authority remain separate.
