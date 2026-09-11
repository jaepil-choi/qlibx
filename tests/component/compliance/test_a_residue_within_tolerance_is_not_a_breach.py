"""`docs/issues/archive/086`. A book executes in whole lots and is marked after its fills, so the
realised weight lands a little off the target the optimiser put on the grid. The shipped
`single_name_cap` compares strictly, so 40 of 82 rebalances in the run that filed the issue were
recorded as violations of a cap the optimiser had respected -- worst excess 0.01%p -- in the same
counter as the one real breach, 4.89%p, and the record's `fix` said to loosen the bound.

Owner ruling, 2026-09-05: a generous tolerance, `max(bound * 1%, 10bp of NAV)`, judged once in
the framework for every rule, overridable on the rule, with the record split into
`held` / `within_tolerance` / `breached` so a generous default hides nothing.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from vqapr.authoring import Compliance, ComplianceFinding
from vqapr.component.compliance.report import (
    VERDICT_BREACHED,
    VERDICT_HELD,
    VERDICT_WITHIN_TOLERANCE,
    StampedFinding,
    default_tolerance,
)
from vqapr.flow.freeze import contract_report
from vqapr.flow.run.compliance import _tolerance_override


def _finding(*, passed: bool, bound: str, excess: str) -> ComplianceFinding:
    return ComplianceFinding(
        passed=passed,
        measured=Decimal(bound) + Decimal(excess),
        bound=Decimal(bound),
        excess=Decimal(excess),
        details={},
        offenders=() if passed else ("A005930",),
    )


def test_the_default_is_one_percent_of_the_bound_floored_at_ten_basis_points() -> None:
    assert default_tolerance(Decimal("0.10")) == Decimal("0.0010"), (
        "10% cap: 0.1%p, 10x the residue"
    )
    assert default_tolerance(Decimal("0.20")) == Decimal("0.0020")
    assert default_tolerance(Decimal("0.005")) == Decimal("0.001"), "a small cap takes the floor"
    assert default_tolerance(Decimal("0")) == Decimal("0.001"), "a zero bound (no-short) too"
    assert default_tolerance(Decimal("-0.10")) == Decimal("0.0010"), "a lower bound, by magnitude"


def test_the_reporters_two_populations_get_two_verdicts() -> None:
    residue = StampedFinding("cap", _finding(passed=False, bound="0.10", excess="0.0001"))
    breach = StampedFinding("cap", _finding(passed=False, bound="0.10", excess="0.0489"))
    clean = StampedFinding("cap", _finding(passed=True, bound="0.10", excess="0"))

    assert residue.tolerance == Decimal("0.0010")
    assert residue.verdict == VERDICT_WITHIN_TOLERANCE and residue.breached is False
    assert breach.verdict == VERDICT_BREACHED and breach.breached is True
    assert clean.verdict == VERDICT_HELD
    # The author's own comparison is untouched: `passed` still says what the rule said.
    assert residue.passed is False and breach.passed is False and clean.passed is True


def test_an_authors_tolerance_overrides_the_default_in_both_directions() -> None:
    residue = _finding(passed=False, bound="0.10", excess="0.0001")
    tight = StampedFinding("cap", residue, tolerance=Decimal("0.00001"))
    loose = StampedFinding(
        "cap", _finding(passed=False, bound="0.10", excess="0.0489"), tolerance=Decimal("0.05")
    )
    assert tight.verdict == VERDICT_BREACHED
    assert loose.verdict == VERDICT_WITHIN_TOLERANCE
    with pytest.raises(ValueError, match="finite non-negative"):
        StampedFinding("cap", residue, tolerance=Decimal("-0.001"))


def test_the_override_is_read_off_the_rule_and_a_wrong_one_is_refused() -> None:
    class Plain(Compliance):
        @property
        def compliance_id(self) -> str:
            return "plain"

        def observe(self, call):  # pragma: no cover - not exercised
            raise NotImplementedError

    class Declared(Plain):
        @property
        def tolerance(self) -> Decimal | None:
            return Decimal("0.005")

    class Wrong(Plain):
        @property
        def tolerance(self):  # type: ignore[override]
            return 0.005

    assert Plain().tolerance is None, "the ABC's default leaves it to the framework"
    assert _tolerance_override(Plain()) is None
    assert _tolerance_override(Declared()) == Decimal("0.005")
    with pytest.raises(TypeError, match="tolerance must be a finite non-negative Decimal"):
        _tolerance_override(Wrong())


def _result(*stamped: StampedFinding) -> SimpleNamespace:
    occurrences = [
        SimpleNamespace(result=SimpleNamespace(report=SimpleNamespace(findings=(item,))))
        for item in stamped
    ]
    return SimpleNamespace(occurrences=occurrences, final_state=SimpleNamespace(lifecycle_trace=()))


def test_the_contract_block_splits_the_run_that_filed_the_issue() -> None:
    """41 held, 40 within tolerance, 1 breached: `ok: false` because of the one, and the other
    two populations are filed beside it with their worst excess rather than folded into it."""
    held = [StampedFinding("cap", _finding(passed=True, bound="0.10", excess="0"))] * 41
    residues = [StampedFinding("cap", _finding(passed=False, bound="0.10", excess="0.0001"))] * 40
    breach = StampedFinding("cap", _finding(passed=False, bound="0.10", excess="0.0489"))

    entry = contract_report(_result(*held, *residues, breach))["cap"]

    assert entry["checked"] == 82
    assert (entry["held"], entry["within_tolerance"], entry["breached"]) == (41, 40, 1)
    assert entry["tolerance"] == "0.0010"
    assert entry["worst_within"] == "0.0001" and entry["worst_breached"] == "0.0489"
    assert entry["ok"] is False
    assert entry["cause"] == (
        "1 of 82 check(s) breached beyond the tolerance 0.0010 (worst excess 0.0489)"
    )
    assert "raise the rule's `tolerance`" in entry["fix"]


def test_a_run_of_residues_alone_is_ok_and_says_how_much_it_tolerated() -> None:
    residues = [StampedFinding("cap", _finding(passed=False, bound="0.10", excess="0.0001"))] * 40

    entry = contract_report(_result(*residues))["cap"]

    assert entry["ok"] is True, "nothing breached beyond the line"
    assert entry["within_tolerance"] == 40 and entry["breached"] == 0 and entry["held"] == 0
    assert entry["worst_within"] == "0.0001" and entry["worst_breached"] is None
    assert "cause" not in entry and "fix" not in entry


def test_a_rule_nobody_checked_still_proves_nothing() -> None:
    entry = contract_report(_result())
    assert entry == {"accepted_intents": 0}
