from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import qlibx
from qlibx import Project
from qlibx.agent import apply_instruction, plan_instruction
from qlibx.alpha import exposure_summary, group_demean, hump, linear_decay, rescale_budget
from qlibx.extensions import load_extension
from qlibx.strategy import (
    DecisionContext,
    DecisionResult,
    StrategyDefinition,
    run_decision,
)


def test_root_api_is_small_and_responsibility_based() -> None:
    assert qlibx.__all__ == [
        "Project",
        "QlibxError",
        "agent",
        "alpha",
        "artifacts",
        "data",
        "ensemble",
        "execution",
        "extensions",
        "portfolio",
        "reporting",
        "research",
        "strategy",
    ]
    assert len(qlibx.__all__) <= 15
    assert not hasattr(qlibx, "run_signed_execution")


def test_fixed_and_flexible_budget_preserve_declared_semantics() -> None:
    weights = pd.DataFrame([[0.2, -0.1, 0.0]], columns=list("abc"))
    fixed = rescale_budget(weights, mode="fixed")
    flexible = rescale_budget(weights, mode="flexible")
    assert fixed.clip(lower=0).sum(axis=1).iloc[0] == pytest.approx(1.0)
    assert fixed.clip(upper=0).sum(axis=1).iloc[0] == pytest.approx(-1.0)
    assert flexible.equals(weights)
    summary = exposure_summary(flexible)
    assert summary.gross.iloc[0] == pytest.approx(0.3)
    assert summary.net.iloc[0] == pytest.approx(0.1)


def test_group_decay_and_hump_are_deterministic() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame([[1.0, 3.0], [2.0, 6.0], [4.0, 8.0]], index=dates)
    groups = pd.DataFrame([["x", "x"]] * 3, index=dates)
    assert group_demean(values, groups).iloc[0].tolist() == [-1.0, 1.0]
    assert linear_decay(values, window=2).iloc[-1, 0] == pytest.approx(10 / 3)
    assert hump(values, maximum_change=1.0).iloc[-1].tolist() == [3.0, 5.0]


def test_child_strategy_cannot_escape_parent_context() -> None:
    dates = pd.date_range("2025-01-01", periods=2)
    frame = pd.DataFrame({"a": [1.0, 2.0]}, index=dates)
    context = DecisionContext(dates[-1], {"returns": frame}, seed=7)
    child = context.child(datasets={"returns": frame.tail(1)})
    definition = StrategyDefinition("s", "sample", {}, ("returns",), "signal")
    result = run_decision(
        definition,
        lambda bounded, _: DecisionResult("signal", bounded.datasets["returns"]),
        child,
    )
    assert result.payload.equals(frame.tail(1))
    future = pd.DataFrame({"a": [3.0]}, index=[dates[-1] + pd.Timedelta(days=1)])
    with pytest.raises(ValueError, match="exceeds parent time bounds"):
        context.child(datasets={"returns": future})


def test_onboarding_is_idempotent_and_extension_is_project_local(tmp_path: Path) -> None:
    Project.initialize(tmp_path)
    project = Project.load(tmp_path)
    instruction = tmp_path / "AGENTS.md"
    instruction.write_text("user text\n", encoding="utf-8")
    first = plan_instruction(project, "AGENTS.md")
    apply_instruction(first)
    second = plan_instruction(project, "AGENTS.md")
    assert second.action == "unchanged"
    assert second.after.count("<!-- qlibx:managed:start -->") == 1
    assert second.after.startswith("user text")

    extension = tmp_path / "qlibx-custom" / "transform.py"
    extension.parent.mkdir(exist_ok=True)
    extension.write_text("def apply(value):\n    return value * 2\n", encoding="utf-8")
    reference, implementation = load_extension(
        project,
        extension_id="double",
        contract="signal_transform",
        contract_version="1",
        source="qlibx-custom/transform.py",
        callable_name="apply",
    )
    assert implementation(3) == 6
    assert reference.source_digest
