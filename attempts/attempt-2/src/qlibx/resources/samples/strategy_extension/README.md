# qlibx project-local Strategy extension

This product-owned example demonstrates the supported local alpha extension lifecycle:

1. copy one explicit Python file into the project's configured extension directory without
   overwriting modified user code;
2. publish an immutable typed signal artifact;
3. validate two fresh Strategy instances against the fixed module contract and exact artifact;
4. receive a `strategy_extension_registration:v1` artifact; and
5. execute only that exact registration ID through the public project facade.

From the initialized project root run:

```powershell
uv run python examples/qlibx_owned/strategy_extension/run.py .
uv run qlibx strategy list .
```

`strategy.py` imports only the curated top-level `qlibx` extension surface. The module is trusted
project code, not a security sandbox. qlibx confines it to the configured extension directory and
checks source/schema identity, but Python import can still execute arbitrary user code.

If `qlibx_extensions/sample_ranked_signal.py` already differs from the bundled source, the script
refuses to overwrite it. Validate the changed file explicitly and use the newly returned
registration artifact ID; qlibx never selects the latest compatible registration automatically.