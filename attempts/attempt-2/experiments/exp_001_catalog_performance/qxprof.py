"""Pytest plugin measuring DuckDB connect, cursor, execute, close, and fsync costs."""

import atexit
import collections
import os
import time

import duckdb

STATS = collections.defaultdict(lambda: [0, 0.0])
_real_connect = duckdb.connect
_real_fsync = os.fsync


class _Wrapped:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            result = self._inner.execute(*args, **kwargs)
            return self if result is self._inner else result
        finally:
            elapsed = time.perf_counter() - start
            entry = STATS["execute"]
            entry[0] += 1
            entry[1] += elapsed
            sql = " ".join(str(args[0]).split())[:72] if args else "?"
            sub = STATS["  sql| " + sql]
            sub[0] += 1
            sub[1] += elapsed

    def cursor(self):
        start = time.perf_counter()
        try:
            return _Wrapped(self._inner.cursor())
        finally:
            entry = STATS["cursor"]
            entry[0] += 1
            entry[1] += time.perf_counter() - start

    def close(self):
        start = time.perf_counter()
        try:
            return self._inner.close()
        finally:
            entry = STATS["close"]
            entry[0] += 1
            entry[1] += time.perf_counter() - start

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _connect(*args, **kwargs):
    start = time.perf_counter()
    try:
        return _Wrapped(_real_connect(*args, **kwargs))
    finally:
        key = "connect(read_only)" if kwargs.get("read_only") else "connect(write)"
        entry = STATS[key]
        entry[0] += 1
        entry[1] += time.perf_counter() - start


def _fsync(fd):
    start = time.perf_counter()
    try:
        return _real_fsync(fd)
    finally:
        entry = STATS["os.fsync"]
        entry[0] += 1
        entry[1] += time.perf_counter() - start


duckdb.connect = _connect
os.fsync = _fsync
_T0 = time.perf_counter()


@atexit.register
def _report():
    total = time.perf_counter() - _T0
    lines = ["", "=" * 72, f"instrumented wall: {total:.2f}s", "=" * 72]
    ranked = sorted(STATS.items(), key=lambda item: -item[1][1])
    for key, (count, seconds) in ranked[:50]:
        lines.append(
            f"{key:34s} n={count:6d} total={seconds:8.2f}s "
            f"avg={seconds / max(count, 1) * 1000:8.2f}ms {seconds / total * 100:5.1f}%"
        )
    print("\n".join(lines))