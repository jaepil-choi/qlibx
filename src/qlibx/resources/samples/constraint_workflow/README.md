# qlibx public constraint workflow

This product-owned example demonstrates the optional current MVP constraint capability through
installed public Python APIs. It is not an optimizer, an alpha claim, or an execution simulation.

Materialize it explicitly from a qlibx project:

```python
from qlibx import QlibxProject

project = QlibxProject.open(".")
project.materialize_sample("constraint-workflow-v1", apply=True)
```

Then run:

```powershell
uv run python examples/qlibx_owned/constraint_workflow/run.py .
```

The signed source portfolio is created without benchmark data. Only the selected constraint
operation resolves the two bounded K200 weights, whose 2024-01-02 observations use the confirmed
next-session 09:00 Asia/Seoul availability. Adjustment applies no-short and
`weight <= max(10%, benchmark weight)`, then floors order deltas to one-share lots. Independent
validation reads the adjustment artifact and benchmark again. The A005930 lot residual remains
slightly above its 31.72% cap, so adjustment completes but validation reports `eligible=false`.

The sample does not add sector, turnover, liquidity, partial-fill, settlement, or OMS behavior.