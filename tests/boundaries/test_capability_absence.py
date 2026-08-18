"""The leaf rule, checked by what a module can reach rather than by what it declares.

Canon refuses an import-linter tool contract, and gives the reason: once a tool contract exists,
type placement starts following the contract string instead of the design, and the boundaries worth
keeping are already enforced by the absence of a path. So this file does not parse imports.

It checks two things instead. The signature half asserts that a leaf receives every panel it needs
as an argument, which is canon's own device — a function that takes values cannot go looking for
them. The capability half runs in a **clean subprocess**, because the in-suite process is useless
for the question: `conftest` imports duckdb session-wide and `vqapr.public` pulls in the data, flow
and evidence layers long before any assertion here would run. Asserting absence in that process
would be guaranteed-red and would say nothing about the leaf.
"""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from inspect import signature

from vqapr.transforms import window

# Canon's own list of what a leaf must not reach for, plus the two this milestone adds
# deliberately: `evidence` because a leaf that could write provenance is no longer a leaf, and
# `duckdb` because reaching a store directly is the exact bypass the point-in-time boundary exists
# to prevent. The two additions are a departure recorded here rather than folded into the citation.
FORBIDDEN = (
    "vqapr.account",
    "vqapr.data",
    "vqapr.evidence",
    "vqapr.exchange",
    "vqapr.flow",
    "vqapr.models",
    "vqapr.runtime",
    "duckdb",
)

LEAF_MODULES = ("vqapr.transforms.window",)


def test_a_leaf_receives_its_values_and_cannot_go_looking_for_them() -> None:
    """The signature is the contract. Every input arrives as an argument."""
    parameters = signature(window.apply_causal).parameters

    assert list(parameters) == ["series", "length", "fn"]
    assert parameters["length"].kind is parameters["length"].KEYWORD_ONLY
    assert parameters["fn"].kind is parameters["fn"].KEYWORD_ONLY

    # No date, no index, no panel, and no store handle: there is nothing here to reach with.
    forbidden_names = {"window", "store", "view", "index", "dates", "panel", "requirement"}
    assert not forbidden_names & set(parameters)

    # The callable is handed values only, so it cannot ask for a position it was not given.
    seen: list[object] = []
    window.apply_causal(
        ((Decimal(1), Decimal(2), Decimal(3)),),
        length=2,
        fn=lambda windows: (seen.append(windows), Decimal(0))[1],
    )
    assert all(isinstance(entry, tuple) for entry in seen)
    assert all(isinstance(value, Decimal) for entry in seen for inner in entry for value in inner)


def test_importing_a_leaf_pulls_in_no_capability_it_should_not_have() -> None:
    """Run in a clean subprocess, because this process already holds every name under test."""
    probe = (
        "import sys\n"
        f"for name in {LEAF_MODULES!r}:\n"
        "    __import__(name)\n"
        f"present = sorted(n for n in {FORBIDDEN!r} if n in sys.modules)\n"
        "print(';'.join(present))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    reached = [name for name in completed.stdout.strip().split(";") if name]
    assert reached == [], f"importing a leaf reached {reached}"


def test_the_probe_itself_can_fail() -> None:
    """A capability check that cannot go red proves nothing, so prove this one can."""
    probe = (
        "import sys\n"
        "import vqapr.public\n"
        f"present = sorted(n for n in {FORBIDDEN!r} if n in sys.modules)\n"
        "print(';'.join(present))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    reached = [name for name in completed.stdout.strip().split(";") if name]
    assert reached, "the public surface reaches these layers, so the probe must observe them"
