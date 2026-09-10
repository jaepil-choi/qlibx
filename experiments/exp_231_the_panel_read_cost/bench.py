"""How much a 3,000-name panel read costs through today's per-name API, versus one 2D block."""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np

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
panel = Panel.from_rows(
    rows,
    dataset_id="p",
    fields=("close",),
    instruments=names,
    keyed_by_instrument=True,
    identity="x",
    source_digest="d",
)
w = panel.window("close", evaluation_time=instants[-1], lookback=RowsLookback(rows=T))


def timeit(label, fn, reps=3):
    best = (
        min(
            ((lambda: (time.perf_counter(), fn(), time.perf_counter()))()[::2] and 0) or 0
            for _ in range(0)
        )
        if False
        else None
    )
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    print(f"{label:58} {min(ts) * 1000:9.1f} ms")


def sample_decide():  # what reversal_5d.py does today
    closes = {}
    for name in w.instruments:
        closes[name] = [Decimal(str(v)) for v in w.values[name] if v is not None]
    eligible = {n: v for n, v in closes.items() if len(v) == T}
    returns = {n: v[-1] / v[0] - Decimal(1) for n, v in eligible.items()}
    return sorted(returns, key=lambda n: (returns[n], n))[:3]


def framework_counts():
    return w.counts()


def framework_current():
    return w.current()


# a 2D block, built once per panel (what a matrix accessor would hold)
block = np.full((T, N), np.nan)
for j, name in enumerate(names):
    block[:, j] = panel.columns["close"][name].to_numpy(zero_copy_only=False)


def matrix_decide():
    m = block[-T:]
    full = ~np.isnan(m).any(axis=0)
    ret = m[-1] / m[0] - 1.0
    ret[~full] = np.inf
    return [names[i] for i in np.argsort(ret, kind="stable")[:3]]


timeit("sample decide (per-name loop + Decimal)", sample_decide)
timeit("PanelWindow.counts() (framework, every read)", framework_counts)
timeit("PanelWindow.current() (framework)", framework_current)
timeit("2D block decide (numpy)", matrix_decide)
timeit(
    "build 2D block from panel (once per panel)",
    lambda: np.column_stack(
        [panel.columns["close"][n].to_numpy(zero_copy_only=False) for n in names]
    ),
)
print("same answer:", sample_decide() == matrix_decide())
