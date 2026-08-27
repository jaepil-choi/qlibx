"""`vqapr new exchange` exists because a first-time-user journey could not finish without it.

Five of the six things a run needs had a scaffold. The Exchange did not -- and the run-spec
template names `exchange:` as required, so every journey reaches it. The user had to learn from a
refusal that only two profiles are permitted, then guess the shape of `listings`: a mapping keyed
by instrument id whose values are `TradeRule`, a type no template, no help text and no skill
section ever named. Six consecutive guesses returned the byte-identical error.

The evaluation stopped there, which is the correct outcome for a measurement and a failing one for
the product. These tests pin the repair.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _cli(project_root: Path, *argv: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, "-m", "vqapr", "--project-root", str(project_root), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, {"raw": (result.stdout or result.stderr)[-400:]}


def test_the_scaffold_is_offered_at_all(tmp_path: Path) -> None:
    """`new exchange` used to be rejected as an invalid choice, naming the five that existed."""
    code, created = _cli(tmp_path, "new", "exchange", "venue", "--out", str(tmp_path / "v.py"))

    assert code == 0, created
    assert created["kind"] == "exchange"


def test_the_emitted_exchange_constructs_without_edits(tmp_path: Path) -> None:
    """The `listings` shape is the thing that could not be guessed, so it must be shown working.

    Executed rather than pattern-matched: a template that merely mentions `TradeRule` would look
    correct and still leave the reader to work out the mapping's key, which is exactly the step
    six guesses failed on.
    """
    _cli(tmp_path, "new", "exchange", "venue", "--out", str(tmp_path / "v.py"))
    namespace: dict = {}

    exec(
        compile((tmp_path / "v.py").read_text(encoding="utf-8"), "v.py", "exec"), namespace
    )
    venue = namespace["Venue"]()

    assert venue.listings, "the emitted Exchange lists nothing, so every instrument would refuse"
    for instrument_id, rule in venue.listings.items():
        assert rule.instrument_id == instrument_id, (
            "a listing key must match its rule's instrument_id -- the invariant whose refusal "
            "gave no further information six times in a row"
        )


def test_the_scaffold_registers_through_the_declaration_it_writes(tmp_path: Path) -> None:
    """A scaffold that emits an unregisterable pair moves the stall rather than removing it."""
    _cli(tmp_path, "new", "exchange", "venue", "--out", str(tmp_path / "v.py"))

    code, registered = _cli(tmp_path, "register", str(tmp_path / "v.yaml"))

    assert code == 0, registered
    assert registered["registered"]["components"] == ["venue"]


def test_the_universe_can_be_named_up_front(tmp_path: Path) -> None:
    """Listing the run's own instruments is the common case, so it must not require an edit."""
    code, created = _cli(
        tmp_path, "new", "exchange", "venue",
        "--instruments", "A005930", "A035420", "A000660",
        "--out", str(tmp_path / "v.py"),
    )
    assert code == 0, created

    namespace: dict = {}
    exec(
        compile((tmp_path / "v.py").read_text(encoding="utf-8"), "v.py", "exec"), namespace
    )

    assert sorted(namespace["Venue"]().listings) == ["A000660", "A005930", "A035420"]


@pytest.mark.parametrize("kind", ["dataset", "execution-input", "agendas", "exchange", "run-spec"])
def test_every_declaration_a_run_needs_has_a_scaffold(kind: str, tmp_path: Path) -> None:
    """The gap was structural: one required declaration had no template while the rest did.

    Parametrized over the whole set so a future addition without a scaffold fails here rather than
    in somebody's first journey.
    """
    argv = ["new", kind, "--out", str(tmp_path / f"{kind}.out")]
    if kind == "exchange":
        argv.insert(2, "venue")

    code, created = _cli(tmp_path, *argv)

    assert code == 0, created


def test_a_stale_installed_skill_is_detectable(tmp_path: Path) -> None:
    """An installed skill that no longer matches the package must SAY so.

    A stale skill is worse than no skill: an agent reads it and is confidently taught a surface
    that no longer exists. This went unnoticed once already -- a repair landed in source, the
    installed copy still described the older surface, and `skill list` reported only
    `installed: true`, so nothing anywhere disagreed. The journey would then have been re-measured
    against the pre-repair surface and stalled in exactly the original place.
    """
    _cli(tmp_path, "skill", "install", "--into", str(tmp_path))

    code, fresh = _cli(tmp_path, "skill", "list", "--into", str(tmp_path))
    assert code == 0, fresh
    assert fresh["current"] is True, "a just-installed skill must report as current"

    installed = tmp_path / ".agents" / "skills" / "vqapr" / "SKILL.md"
    installed.write_text(installed.read_text(encoding="utf-8") + "\ndrifted\n", encoding="utf-8")

    code, drifted = _cli(tmp_path, "skill", "list", "--into", str(tmp_path))

    assert drifted["current"] is False, "a drifted skill reported as current is the whole defect"
    assert "install" in drifted.get("stale", ""), "the report must name the command that fixes it"
