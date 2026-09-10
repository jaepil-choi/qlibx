"""Measure the scan bounds and block shapes the 0.13.0 store builds for one run -- not imagine them.

Wraps `DuckDbObservationStore._scan_bounds`, `Panel.from_table` and `Panel.window` around a real
`vqapr run`, printing to stderr what each returned. The stepper quotes these shapes (17 x 10,
11 x 10, 38 x 10, 10 x 10) beside the trace frames that built them:

    uv run python experiments/exp_238_the_scenario_trace_0_13_0/probe_panel.py \
        --project-root DIR run sample-features-run --force
"""

from __future__ import annotations

import contextlib
import io
import sys

from vqapr.cli.main import main
from vqapr.data import panel as panel_module
from vqapr.data import store as store_module

_bounds = store_module.DuckDbObservationStore._scan_bounds
_from_table = panel_module.Panel.from_table.__func__
_window = panel_module.Panel.window
_windows_seen = 0


def scan_bounds(self, source, registration, declared, evaluation_time):
    out = _bounds(self, source, registration, declared, evaluation_time)
    print(
        f"PROBE _scan_bounds {declared[0].dataset_id} lookback={declared[0].lookback!r}"
        f" -> {out[0].isoformat()} .. {out[1].isoformat()}",
        file=sys.stderr,
    )
    return out


def from_table(cls, table, **kw):
    built = _from_table(cls, table, **kw)
    shapes = {name: block.shape for name, block in built.blocks.items()}
    print(
        f"PROBE Panel.from_table {built.dataset_id} instants={len(built.instants)}"
        f" names={len(built.instruments)} blocks={shapes} bounds={built.bounds}"
        f" first={built.instants[0].isoformat()} last={built.instants[-1].isoformat()}",
        file=sys.stderr,
    )
    return built


def window(self, field, **kw):
    global _windows_seen
    opened = _window(self, field, **kw)
    _windows_seen += 1
    if _windows_seen <= 2:
        print(
            f"PROBE window#{_windows_seen} field={field} at={kw.get('evaluation_time')}"
            f" matrix.shape={opened.matrix().shape}",
            file=sys.stderr,
        )
    return opened


store_module.DuckDbObservationStore._scan_bounds = scan_bounds
panel_module.Panel.from_table = classmethod(from_table)
panel_module.Panel.window = window

if __name__ == "__main__":
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(sys.argv[1:])
    print("exit", code, file=sys.stderr)
