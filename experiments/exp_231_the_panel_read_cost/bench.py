"""How much a 3,000-name panel read costs through the per-name API, versus the field's block.

Issue `docs/issues/096`; record `232` is the fix. Before the record the panel held one Arrow
array per name and every accessor walked the names in Python; after it a field is one block
and `PanelWindow.matrix()` is a view of it. The sample decision is written both ways below so
the two answers can be compared as well as timed.

    uv run python experiments/exp_231_the_panel_read_cost/bench.py
"""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pyarrow as pa

from vqapr.data.lookback import RowsLookback
from vqapr.data.panel import Panel

N, T = 3000, 6
base = datetime(2022, 1, 3, 15, 30, tzinfo=UTC)
instants = [base + timedelta(days=i) for i in range(T)]
names = [f"K{n:06d}" for n in range(N)]
rows = [
    {"available_at": t, "instrument": name, "close": 100.0 + (i * 7 + j) % 13}
    for i, t in enumerate(instants)
    for j, name in enumerate(names)
]
table = pa.Table.from_pylist(
    rows,
    schema=pa.schema(
        [
            ("available_at", pa.timestamp("us", tz="UTC")),
            ("instrument", pa.string()),
            ("close", pa.float64()),
        ]
    ),
)


def timeit(label, fn, reps=3):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    print(f"{label:58} {min(ts) * 1000:9.1f} ms")


def build():
    return Panel.from_table(
        table,
        dataset_id="p",
        fields=("close",),
        instruments=names,
        keyed_by_instrument=True,
        identity="x",
        source_digest="d",
    )


panel = build()
w = panel.window("close", evaluation_time=instants[-1], lookback=RowsLookback(rows=T))


def sample_decide_per_name():  # the sample strategy before record 233: a loop and Decimals
    closes = {}
    for name in w.instruments:
        closes[name] = [Decimal(str(v)) for v in w.values[name] if v is not None]
    eligible = {n: v for n, v in closes.items() if len(v) == T}
    returns = {n: v[-1] / v[0] - Decimal(1) for n, v in eligible.items()}
    return sorted(returns, key=lambda n: (returns[n], n))[:3]


def sample_decide_matrix():  # the sample strategy after record 233: the block
    closes = w.matrix()
    full = ~np.isnan(closes).any(axis=0)
    returns = closes[-1] / closes[0] - 1.0
    order = sorted((returns[j], w.instruments[j]) for j in np.flatnonzero(full))
    return [name for _, name in order[:3]]


timeit("build the panel from the scan's columns (once per run)", build)
timeit("sample decide, per-name loop + Decimal (before 233)", sample_decide_per_name)
timeit("sample decide on matrix() (after 233)", sample_decide_matrix)
timeit("PanelWindow.counts() (framework, every read)", w.counts)
timeit("PanelWindow.current()", w.current)
timeit("PanelWindow.latest()", w.latest)
timeit("PanelWindow.matrix() (a view)", w.matrix)
print("same answer:", sample_decide_per_name() == sample_decide_matrix())
