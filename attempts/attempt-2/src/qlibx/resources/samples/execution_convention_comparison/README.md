# qlibx execution-convention comparison

This opt-in example demonstrates `UC-ALPHA-CHILD-001` through installed public APIs:

1. one Strategy invocation publishes an immutable `decision_intent:v1` parent;
2. exact parent artifact selection creates isolated next-close and next-open children;
3. the children use distinct execution times, price roles, profiles, Accounts, and lineage without
   rerunning the Strategy;
4. open and close observations have separate, explicit availability instants; and
5. attempting to use the close-available price at the open event fails before an execution result
   or Account mutation.

From an initialized project root run:

```powershell
uv run python examples/qlibx_owned/execution_convention_comparison/run.py .
```

The bundled prices are deterministic contract evidence, not a market-quality or execution-realism
claim. Both profiles assume a single full-batch reference price and do not model market impact,
intraday paths, or production OMS behavior.
