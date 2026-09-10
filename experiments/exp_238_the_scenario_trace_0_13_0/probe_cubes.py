"""Bake the cubes a `--jobs` batch of the given runs would bake, into OUT, and list what is on disk.

The batch removes its directory when it returns, so the driver trace never shows the files; this
runs `_bake_for_batch` the way `batch_cubes` does and prints each file with its size and shape:

    uv run python experiments/exp_238_the_scenario_trace_0_13_0/probe_cubes.py \
        PROJECT OUT_DIR sample-factor-run sample-stoploss-run
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from vqapr.flow import orchestration
from vqapr.project.store import Workspace

if __name__ == "__main__":
    project = Path(sys.argv[1])
    out = Path(sys.argv[2])
    runs = sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    workspace = Workspace.open(project)
    for run_id in runs:
        reads = orchestration._reads(workspace, workspace.run_definition(run_id))
        print("reads", run_id, {name: sorted(fields) for name, fields in reads.items()})
    orchestration._bake_for_batch(workspace, runs, out)
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        extra = ""
        if path.suffix == ".npy":
            array = np.load(path, mmap_mode="r")
            extra = f"shape={array.shape} dtype={array.dtype}"
        elif path.suffix == ".json":
            extra = path.read_text(encoding="utf-8")[:300].replace("\n", " ")
        print(f"{path.relative_to(out)}  {path.stat().st_size} B  {extra}")
