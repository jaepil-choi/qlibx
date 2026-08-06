# qlibx public daily closed-loop journey

This product-owned example demonstrates the current next-session-close simulation through public
Python APIs. It uses eight unchanged bounded rows derived from the repository DW source. It is not
an alpha-performance or production-execution claim.

Materialize it explicitly from a qlibx project:

```python
from qlibx import QlibxProject

project = QlibxProject.open(".")
project.materialize_sample("daily-closed-loop-v1", apply=True)
```

Then run:

```powershell
uv run python examples/qlibx_owned/daily_closed_loop/run.py .
```

The sample makes two decisions, executes each at the next session close, and shows actual Fill/Mark
feedback, Strategy Memory, session performance, final Account state, and portable artifacts. Its
profile assumes eligible-order full fills, cash/holding/lot clipping, zero market impact, and
instant settlement. It does not model intraday paths, pending/cancel orders, or an OMS.