"""Run one command and report its wall time and peak memory (process tree, sampled every 0.25 s).

    PYTHONUTF8=1 uv run python experiments/exp_250_ff3_through_vqapr/measure.py -- <command...>

Prints the command's stdout, then one JSON line: wall seconds, peak private bytes and peak working
set summed over the process and its children (the `uv run` launcher spawns the real interpreter).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import psutil


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    t0 = time.perf_counter()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    peak = {"private": 0, "rss": 0}
    done = threading.Event()

    def sample() -> None:
        root = psutil.Process(proc.pid)
        while not done.is_set():
            try:
                tree = [root, *root.children(recursive=True)]
                priv = rss = 0
                for p in tree:
                    try:
                        m = p.memory_info()
                        priv += getattr(m, "private", m.vms)
                        rss += m.rss
                    except psutil.Error:
                        pass
                peak["private"] = max(peak["private"], priv)
                peak["rss"] = max(peak["rss"], rss)
            except psutil.Error:
                pass
            time.sleep(0.25)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    out, _ = proc.communicate()
    done.set()
    th.join()
    sys.stdout.write(out.decode("utf-8", errors="replace"))
    print(json.dumps({
        "measure": " ".join(argv[-3:]),
        "returncode": proc.returncode,
        "wall_s": round(time.perf_counter() - t0, 1),
        "peak_private_gb": round(peak["private"] / 1e9, 2),
        "peak_working_set_gb": round(peak["rss"] / 1e9, 2),
    }))


if __name__ == "__main__":
    main()
