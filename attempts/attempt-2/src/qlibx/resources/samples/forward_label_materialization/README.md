# qlibx forward-label PIT materialization

This opt-in example demonstrates `UC-PIT-001` through the installed public surface:

1. price inputs are registered without a `horizon_end` semantic binding;
2. direct materialization fails before calculation and leaves failure evidence only;
3. an explicit immutable horizon registration is added;
4. a new invocation links the prior error and materializes only labels available at its frozen
   evaluation time; and
5. a later invocation observes the next horizon without changing earlier artifacts.

From an initialized project root run:

```powershell
uv run python examples/qlibx_owned/forward_label_materialization/run.py .
```

The bundled values are deterministic contract evidence, not a market-quality or predictive-power
claim. The sample never infers `horizon_end`, does not create a stored signal, and does not access or
mutate Account or Strategy state.
