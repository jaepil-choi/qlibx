"""A batch's cube versus each worker's own scan: bake once, then map, for 309 names and for all.

    uv run python experiments/exp_236_the_panel_memory/measure_cube.py

Bakes `close` of the synthetic source (gen_source.py, beside this file as equity_daily.parquet)
into a scratch cube directory, then in fresh processes builds a run's panel two ways -- a scan
(what every worker did before record 236) and a slice of the memory-mapped cube -- reporting
the build time and what the process holds privately.
"""
import ctypes, ctypes.wintypes as w, multiprocessing as mp, shutil, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

class PMCX(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t)] + [(f"q{i}", ctypes.c_size_t) for i in range(6)] + \
               [("PrivateUsage", ctypes.c_size_t)]
def own():
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMCX), w.DWORD]
    p = PMCX(); p.cb = ctypes.sizeof(PMCX)
    assert psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.WorkingSetSize / 1e9, p.PeakWorkingSetSize / 1e9, p.PrivateUsage / 1e9

HERE = Path(__file__).parent
FIRST, LAST = datetime(2015, 1, 2, 16, tzinfo=timezone.utc), datetime(2026, 4, 30, 16, tzinfo=timezone.utc)
START, END = datetime(2019, 1, 2, tzinfo=timezone.utc), datetime(2026, 4, 30, tzinfo=timezone.utc)

def _catalog():
    from vqapr.data.datasets import DatasetRegistration
    from vqapr.data.scan import ColumnType
    from vqapr.data.sources import SourceSpec
    from vqapr.domain.identifiers import dataset_id, source_id
    from vqapr.domain.shapes import Grain
    source = SourceSpec.of("equity_daily", HERE / "equity_daily.parquet")
    registration = DatasetRegistration(
        dataset_id=dataset_id("equity_daily"), source=source_id("equity_daily"), instrument_field="instrument",
        available_at="available_at", key_fields=("available_at", "instrument"), fields={"close": "close"},
        grain=Grain("instrument_instant"), span=(FIRST, LAST), field_types={"close": ColumnType.DOUBLE},
    )
    class Catalog:
        def dataset(self, raw): return registration
        def source(self, raw): return source
    return Catalog(), registration, source

def bake(root: Path) -> float:
    from vqapr.data import cube
    from vqapr.data.scan import ScanSession
    from vqapr.data.sources import physical_digest
    _, registration, source = _catalog()
    t0 = time.perf_counter()
    with ScanSession() as session:
        cube.bake(root, registration=registration, source=source, source_digest=physical_digest(source.path),
                  fields=("close",), session=session)
    return time.perf_counter() - t0

def worker(mode, root, n, report):
    from vqapr.data.lookback import CalendarLookback
    from vqapr.data.requirements import DataRequirement
    from vqapr.data.scan import ScanSession
    from vqapr.data.store import DuckDbObservationStore
    catalog, _, _ = _catalog()
    base = own()
    requirement = DataRequirement.of("equity_daily", "close", lookback=CalendarLookback(days=160))
    names = tuple(f"A{i:05d}" for i in range(4975)) if n == 4975 else tuple(f"A{i:05d}" for i in range(0, 4975, 16))[:n]
    session = ScanSession()
    store = DuckDbObservationStore(catalog, session=session, horizon=(START, END), requirements=(requirement,),
                                   cubes=Path(root) if mode == "cube" else None)
    t0 = time.perf_counter()
    window, _ = store.panel_window((requirement,), "close", evaluation_time=START, instruments=names, consumer_id="probe")
    built = time.perf_counter() - t0
    at, touched, t1 = START, 0, time.perf_counter()
    while at <= END:
        window, _ = store.panel_window((requirement,), "close", evaluation_time=at, instruments=names, consumer_id="probe")
        window.matrix().sum(); touched += 1; at += timedelta(days=1)
    walked = time.perf_counter() - t1
    rss, peak, priv = own()
    report.put((mode, n, round(built, 2), round(walked, 2), touched, round(rss - base[0], 3), round(peak, 3), round(priv - base[2], 3)))
    session.close()

if __name__ == "__main__":
    mp.set_start_method("spawn")
    root = Path(tempfile.mkdtemp(prefix="vqapr-cubes-"))
    try:
        took = bake(root)
        size = sum(p.stat().st_size for p in (root / "equity_daily").iterdir()) / 1e6
        print(f"bake: {took:.1f} s, {size:.0f} MB on disk (all 4,975 names x every instant, one field)")
        print(f"{'':6} {'names':>6} {'build s':>8} {'walk s':>7} {'windows':>8} {'RSS +GB':>8} {'peak GB':>8} {'private +GB':>12}")
        for mode in ("scan", "cube"):
            for n in (309, 4975):
                report = mp.Queue()
                p = mp.Process(target=worker, args=(mode, str(root), n, report)); p.start()
                row = report.get(); p.join()
                m, n, built, walked, touched, rss, peak, priv = row
                print(f"{m:6} {n:6} {built:8.2f} {walked:7.2f} {touched:8} {rss:8.3f} {peak:8.3f} {priv:12.3f}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
