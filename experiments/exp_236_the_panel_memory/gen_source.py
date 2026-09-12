"""Synthetic equity-daily of the reported shape: ~4,975 names, 2015-2026 sessions, ~8.7M rows."""
import sys, numpy as np, pyarrow as pa, pyarrow.parquet as pq, pandas as pd
out = sys.argv[1]
rng = np.random.default_rng(7)
sessions = pd.bdate_range("2015-01-02", "2026-04-30", tz="UTC")   # ~2,960 sessions
S = len(sessions); N = 4975
names = np.array([f"A{i:05d}" for i in range(N)])
# each name alive on a contiguous range; mean life ~ 8.7M / 4975 = ~1750 sessions
starts = rng.integers(0, S // 2, N); lengths = rng.integers(600, S, N)
ends = np.minimum(starts + lengths, S)
inst_idx = np.concatenate([np.full(e - s, i, dtype=np.int32) for i, (s, e) in enumerate(zip(starts, ends))])
sess_idx = np.concatenate([np.arange(s, e, dtype=np.int32) for s, e in zip(starts, ends)])
order = np.lexsort((inst_idx, sess_idx))            # sorted by session, then name
inst_idx, sess_idx = inst_idx[order], sess_idx[order]
R = len(inst_idx)
table = pa.table({
    "available_at": pa.array(sessions.values[sess_idx] + np.timedelta64(16, "h"), type=pa.timestamp("us", tz="UTC")),
    "instrument": pa.array(names[inst_idx]),
    "close": pa.array(rng.lognormal(3, 1, R)),
    "volume": pa.array(rng.lognormal(12, 1, R)),
    "open": pa.array(rng.lognormal(3, 1, R)),
    "high": pa.array(rng.lognormal(3, 1, R)),
    "low": pa.array(rng.lognormal(3, 1, R)),
    "turnover": pa.array(rng.lognormal(20, 1, R)),
})
pq.write_table(table, out, compression="snappy")
import os; print(f"rows={R:,} sessions={S} names={N} bytes={os.path.getsize(out)/1e6:.0f} MB")
