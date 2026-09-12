"""Do K processes reading one array file hold it K times or once? Copy (np.load) vs mmap."""
import ctypes, ctypes.wintypes as w, multiprocessing as mp, sys, time
from pathlib import Path
import numpy as np

class MS(ctypes.Structure):
    _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD), ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64)] + [(f"u{i}", ctypes.c_uint64) for i in range(5)]
class PMCX(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t)] + [(f"q{i}", ctypes.c_size_t) for i in range(6)] + \
               [("PrivateUsage", ctypes.c_size_t)]
def avail_gb():
    ms = MS(); ms.dwLength = ctypes.sizeof(MS)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)), ctypes.GetLastError(); return ms.ullAvailPhys / 1e9
def own():
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMCX), w.DWORD]
    p = PMCX(); p.cb = ctypes.sizeof(PMCX)
    assert psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.WorkingSetSize / 1e9, p.PrivateUsage / 1e9

def child(mode, path, cols, report, release):
    base = own()
    t0 = time.perf_counter()
    if mode == "copy":
        a = np.load(path)                              # bytes copied into this process
        total = float(a.sum())
    else:
        a = np.load(path, mmap_mode="r")               # a window onto the OS page cache
        total = float(a[:cols].sum()) if cols else float(a.sum())   # touch only the pages we need
    took = time.perf_counter() - t0
    rss, priv = own()
    report.put((mode, round(took, 2), round(rss - base[0], 3), round(priv - base[1], 3), total))
    release.wait()

if __name__ == "__main__":
    mp.set_start_method("spawn")
    here = Path(__file__).parent; path = here / "cube_close.npy"
    if not path.exists():
        np.save(path, np.random.default_rng(1).random((4975, 10_000)))   # 4,975 names x 10,000 instants
    size = path.stat().st_size / 1e9
    print(f"file: {size:.2f} GB, one float64 array (4,975 names x 10,000 instants), name-major")
    K = 4
    for mode, cols in (("copy", 0), ("mmap", 0), ("mmap", 309)):
        report, release = mp.Queue(), mp.Event()
        before = avail_gb()
        ps = [mp.Process(target=child, args=(mode, str(path), cols, report, release)) for _ in range(K)]
        for p in ps: p.start()
        rows = [report.get() for _ in ps]
        time.sleep(1.0)
        during = avail_gb()
        release.set()
        for p in ps: p.join()
        label = f"{mode}" + (f", touch {cols} of 4,975 names" if cols else ", touch all")
        print(f"\n== {K} processes, {label} ==")
        print(f"  system available memory: {before:.2f} -> {during:.2f} GB  (drop {before - during:.2f} GB; "
              f"K x file = {K * size:.2f} GB, 1 x file = {size:.2f} GB)")
        for m, took, rss, priv, _ in rows:
            print(f"  child: {took:5.2f} s   RSS +{rss:.2f} GB   private +{priv:.2f} GB")
