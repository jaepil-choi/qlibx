"""Peak working set of one datamodel-shaped read: build the panel, then window it per session.

usage: measure_panel.py N_INSTRUMENTS full|horizon RUN_START RUN_END [LOOKBACK_DAYS]
`full` builds the store with no horizon (the registered span, what every run did before record
235); `horizon` hands the store the run's period, so the panel holds only the run's horizon.
"""
import ctypes, ctypes.wintypes as w, sys, time, gc
from datetime import datetime, timedelta, timezone
from pathlib import Path

class PMC(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t)] + [(f"q{i}", ctypes.c_size_t) for i in range(6)]
_k32, _psapi = ctypes.windll.kernel32, ctypes.windll.psapi
_k32.GetCurrentProcess.restype = w.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMC), w.DWORD]
_psapi.GetProcessMemoryInfo.restype = w.BOOL
def mem():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    assert _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb), ctypes.GetLastError()
    return pmc.WorkingSetSize / 1e9, pmc.PeakWorkingSetSize / 1e9
def mark(label):
    cur, peak = mem(); print(f"  {label:<38} now {cur:5.2f} GB   peak {peak:5.2f} GB", flush=True)

n = int(sys.argv[1]); mode = sys.argv[2]
run_start = datetime.fromisoformat(sys.argv[3]).replace(tzinfo=timezone.utc)
run_end = datetime.fromisoformat(sys.argv[4]).replace(tzinfo=timezone.utc)
days = int(sys.argv[5]) if len(sys.argv) > 5 else 160
here = Path(__file__).parent

import vqapr
from vqapr.data.sources import SourceSpec
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.requirements import DataRequirement
from vqapr.data.lookback import CalendarLookback
from vqapr.data.scan import ColumnType, ScanSession
from vqapr.domain.shapes import Grain
from vqapr.domain.identifiers import dataset_id, source_id
print(f"vqapr from {Path(vqapr.__file__).parents[2]}  N={n} mode={mode} period={run_start.date()}..{run_end.date()} lookback={days}d")
mark("after imports")
import os
if os.environ.get("THREADS"):
    from vqapr.data import scan as _scan
    _orig = _scan._configure
    def _patched(con):
        con = _orig(con); con.execute(f"SET threads={int(os.environ['THREADS'])}"); return con
    _scan._configure = _patched
    print(f"  duckdb threads={os.environ['THREADS']} (cpu_count={os.cpu_count()})")

source = SourceSpec.of("equity_daily", here / "equity_daily.parquet")
first, last = datetime(2015, 1, 2, 16, tzinfo=timezone.utc), datetime(2026, 4, 30, 16, tzinfo=timezone.utc)
lookback = CalendarLookback(days=days)
span = (first, last)
registration = DatasetRegistration(
    dataset_id=dataset_id("equity_daily"), source=source_id("equity_daily"), instrument_field="instrument",
    available_at="available_at", key_fields=("available_at", "instrument"), fields={"close": "close"},
    grain=Grain("instrument_instant"), span=span, field_types={"close": ColumnType.DOUBLE},
)
class Catalog:
    def dataset(self, raw): return registration
    def source(self, raw): return source
instruments = tuple(f"A{i:05d}" for i in range(0, 4975, 16))[:n]
requirement = DataRequirement.of("equity_daily", "close", lookback=lookback)

session = ScanSession()
store = (
    DuckDbObservationStore(Catalog(), session=session)
    if mode == "full"
    else DuckDbObservationStore(
        Catalog(), session=session, horizon=(run_start, run_end), requirements=(requirement,)
    )
)
t0 = time.perf_counter()
window, access = store.panel_window((requirement,), "close", evaluation_time=run_start, instruments=instruments, consumer_id="probe")
gc.collect()
mark(f"panel built ({time.perf_counter() - t0:.1f} s)")
panel = window.panel
held = panel.block("close").nbytes if hasattr(panel, "blocks") else sum(a.nbytes for a in panel.columns["close"].values())
print(f"  panel: {len(panel.instants)} instants x {len(panel.names)} names; held {held / 1e6:.1f} MB")
# walk the run's sessions the way the loop does: one window per session, touch the matrix if it exists
at = run_start; touched = 0
while at <= run_end:
    window, access = store.panel_window((requirement,), "close", evaluation_time=at, instruments=instruments, consumer_id="probe")
    if hasattr(window, "matrix"):
        window.matrix().sum()
    else:
        window.latest()
    touched += 1; at += timedelta(days=1)
mark(f"after {touched} daily windows")
session.close()
