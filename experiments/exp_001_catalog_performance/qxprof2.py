"""Pytest plugin measuring ObservationStore query internals."""

import atexit
import collections
import time

import pandas as pd

from qlibx.data import registry, store

STATS = collections.defaultdict(lambda: [0, 0.0])


def _wrap(owner, name, label):
    original = getattr(owner, name)

    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            entry = STATS[label]
            entry[0] += 1
            entry[1] += time.perf_counter() - start

    setattr(owner, name, wrapper)


_wrap(store.ObservationStore, "query", "ObservationStore.query")
_wrap(registry, "file_hash", "file_hash via registry")
_wrap(store, "file_hash", "file_hash via store")
_wrap(store, "normalize_timestamps", "normalize_timestamps")
_wrap(pd, "read_parquet", "pd.read_parquet")
_wrap(pd, "read_csv", "pd.read_csv")
_T0 = time.perf_counter()


@atexit.register
def _report():
    total = time.perf_counter() - _T0
    lines = ["", "=" * 72, f"instrumented wall: {total:.2f}s", "=" * 72]
    for key, (count, seconds) in sorted(STATS.items(), key=lambda item: -item[1][1]):
        lines.append(
            f"{key:34s} n={count:6d} total={seconds:8.2f}s "
            f"avg={seconds / max(count, 1) * 1000:8.2f}ms {seconds / total * 100:5.1f}%"
        )
    print("\n".join(lines))