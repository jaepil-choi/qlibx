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

import pytest

# Canon's own list of what a leaf must not reach for, plus the two this milestone adds
# deliberately: the recorder because a leaf that could write provenance is no longer a leaf, and
# `duckdb` because reaching a store directly is the exact bypass the point-in-time boundary exists
# to prevent. The two additions are a departure recorded here rather than folded into the citation.
# The recorder was `vqapr.evidence` until record `188` dissolved that package: `TableSpec` and
# `InvocationRecorder` are the authoring contract's, and the failure envelope moved into `flow`
# (already listed), so one name covers what two did.
FORBIDDEN = (
    # `vqapr.account` was listed until record `268` folded the package into `domain/account.py`,
    # where the mark values `report.metrics` reads live beside the Account authority, so the
    # module can no longer separate them; the leaves still take no account as an argument.
    "vqapr.data",
    "vqapr.component.strategy.recorder",
    "vqapr.component.exchange",
    "vqapr.run",
    # `vqapr.runtime` was listed here until one-shape Step 7 (record 162) moved its agendas to
    # `domain/` (which a leaf may import) and its envelopes into `flow/loop` (already listed).
    "duckdb",
)

# Every leaf canon names, not just the one whose signature this file also checks. A probe that
# covers one module of five certifies one module of five: the other four could acquire a forbidden
# import and the boundary suite would stay green. The alphas of the next milestone import all of
# them, so the coverage has to precede the code that leans on it.
LEAF_MODULES = (
    "vqapr.signals.transform",
    "vqapr.signals.evaluation",
    "vqapr.report.metrics",
)


@pytest.mark.parametrize("leaf", LEAF_MODULES)
def test_importing_a_leaf_pulls_in_no_capability_it_should_not_have(leaf: str) -> None:
    """Run in a clean subprocess, because this process already holds every name under test.

    One subprocess per leaf, so a breach names the module that caused it. Importing them together
    would prove only that *some* leaf reached a layer, which is not a fact anyone can act on.
    """
    probe = (
        "import sys\n"
        f"__import__({leaf!r})\n"
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
    assert reached == [], f"importing {leaf} reached {reached}"


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
