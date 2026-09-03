"""Every self-contained showcase completes, driven by the test suite rather than by hand.

`docs/issues/052`: five of nine showcases were broken by ordinary contract changes and nothing
noticed, because nothing in `pytest` ran them. The five were repaired (records `131`, `133`), and
this file is the second half of that issue -- the gate. A showcase that a contract change breaks
now fails `test_all` (`uv run pytest tests/ -q -m ""`), which is what a handoff must pass.

Each showcase is one `run.py` with a `main()` that raises on any mismatch it checks, so the
driver is a subprocess and an exit code. Run from the repository root, as a reader would.

**`show_003_real_data_long_short` is not here, deliberately.** It reads the local `data/DW`
warehouse, which is outside the repository (`.gitignore`), so a machine without it cannot run
the showcase at all. A conditional skip would report that machine as green while running one
showcase fewer -- and in this suite a skip is a test that did not run (campaign gate rules). It
stays a hand-run step before a release; `.agent/project.yaml`'s `test_all` comment says so.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SHOWCASES = REPOSITORY / "showcases"
HAND_RUN = frozenset({"show_003_real_data_long_short"})


def _self_contained() -> list[str]:
    names = sorted(
        path.name
        for path in SHOWCASES.iterdir()
        if path.is_dir() and path.name.startswith("show_") and (path / "run.py").is_file()
    )
    return [name for name in names if name not in HAND_RUN]


def test_the_gate_covers_every_showcase_but_the_hand_run_one() -> None:
    """A new showcase is collected without editing this file; a missing one is a failure."""
    found = _self_contained()
    assert len(found) == 8, found
    assert HAND_RUN <= {path.name for path in SHOWCASES.iterdir()}, "show_003 has moved"


@pytest.mark.slow
@pytest.mark.parametrize("showcase", _self_contained())
def test_showcase_completes(showcase: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(SHOWCASES / showcase / "run.py")],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONUTF8": "1"},
        check=False,
    )
    assert completed.returncode == 0, (
        f"{showcase} exited {completed.returncode}\n--- stdout (tail) ---\n"
        f"{completed.stdout[-2000:]}\n--- stderr (tail) ---\n{completed.stderr[-4000:]}"
    )
