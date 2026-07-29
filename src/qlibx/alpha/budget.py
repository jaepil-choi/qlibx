"""Weight-scaling (budget) policies.

A scaling rule is a registered ``BudgetPolicySpec``, so a project can add one without
editing this module. Every policy reports the budget each side actually used and the
leftover it did not, which is what keeps a flexible budget observable downstream.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from qlibx.errors import unknown_name

SideScales = tuple[pd.Series, pd.Series]


@dataclass(frozen=True, slots=True)
class BudgetPolicySpec:
    """One weight-scaling rule.

    ``resolve`` receives the per-date realized side exposure and the declared side
    budgets, and returns the ``(long_scale, short_scale)`` applied to each side. A
    missing scale means the side has no candidates and collapses to zero.
    """

    name: str
    policy_id: str
    version: str
    summary: str
    unused_budget_behavior: str
    resolve: Callable[[pd.Series, pd.Series, float, float], SideScales]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "policy_id": self.policy_id,
            "version": self.version,
            "summary": self.summary,
            "unused_budget_behavior": self.unused_budget_behavior,
        }


class BudgetPolicyRegistry:
    """Name-to-``BudgetPolicySpec`` registry backing every weight-scaling call."""

    def __init__(self) -> None:
        self._policies: dict[str, BudgetPolicySpec] = {}

    def register(
        self, spec: BudgetPolicySpec, *, replace_existing: bool = False
    ) -> BudgetPolicySpec:
        if spec.name in self._policies and not replace_existing:
            raise ValueError(f"budget policy is already registered: {spec.name}")
        self._policies[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._policies.pop(name, None)

    def get(self, name: str) -> BudgetPolicySpec:
        try:
            return self._policies[name]
        except KeyError as error:
            raise unknown_name(
                "QLIBX_BUDGET_POLICY_UNKNOWN", "budget policy", name, self._policies
            ) from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._policies))

    def describe(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._policies[name].describe() for name in self.names())


BUDGET_POLICIES = BudgetPolicyRegistry()


def register_budget_policy(
    spec: BudgetPolicySpec, *, replace_existing: bool = False
) -> BudgetPolicySpec:
    """Register a project-local weight-scaling rule alongside the built-ins."""
    return BUDGET_POLICIES.register(spec, replace_existing=replace_existing)


def budget_policy(name: str) -> BudgetPolicySpec:
    return BUDGET_POLICIES.get(name)


def list_budget_policies() -> tuple[dict[str, Any], ...]:
    return BUDGET_POLICIES.describe()


def _side_scales(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    return (
        long_budget / long_sum.replace(0.0, pd.NA),
        short_budget / short_sum.replace(0.0, pd.NA),
    )


def _fixed(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    return _side_scales(long_sum, short_sum, long_budget, short_budget)


def _flexible(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    long_scale, short_scale = _side_scales(long_sum, short_sum, long_budget, short_budget)
    return long_scale.clip(upper=1.0), short_scale.clip(upper=1.0)


register_budget_policy(
    BudgetPolicySpec(
        name="fixed",
        policy_id="qlibx.alpha.budget.fixed",
        version="1",
        summary="Scale each side to exactly its declared budget when candidates exist.",
        unused_budget_behavior="each side with candidates is scaled up to its full budget",
        resolve=_fixed,
    )
)
register_budget_policy(
    BudgetPolicySpec(
        name="flexible",
        policy_id="qlibx.alpha.budget.flexible",
        version="1",
        summary="Treat each side budget as a maximum and never scale a side upward.",
        unused_budget_behavior="unused budget is preserved and reported as leftover",
        resolve=_flexible,
    )
)


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Rescaled weights plus the leftover budget each side did not use."""

    weights: pd.DataFrame
    policy_id: str
    policy_version: str
    long_budget: float
    short_budget: float
    long_used: pd.Series
    short_used: pd.Series
    long_leftover: pd.Series
    short_leftover: pd.Series


def apply_budget(
    weights: pd.DataFrame,
    *,
    policy: str = "fixed",
    long_budget: float = 1.0,
    short_budget: float = 1.0,
) -> BudgetResult:
    """Apply a registered weight-scaling policy and report the leftover budget."""
    if long_budget < 0 or short_budget < 0:
        raise ValueError("side budgets must be non-negative")
    spec = BUDGET_POLICIES.get(policy)
    positive = weights.clip(lower=0.0)
    negative = weights.clip(upper=0.0)
    long_sum = positive.sum(axis=1)
    short_sum = -negative.sum(axis=1)
    long_scale, short_scale = spec.resolve(long_sum, short_sum, long_budget, short_budget)
    result = positive.mul(long_scale.fillna(0.0), axis=0)
    result += negative.mul(short_scale.fillna(0.0), axis=0)
    result = result.where(weights.notna(), pd.NA)
    long_used = result.clip(lower=0.0).sum(axis=1)
    short_used = -result.clip(upper=0.0).sum(axis=1)
    return BudgetResult(
        weights=result,
        policy_id=spec.policy_id,
        policy_version=spec.version,
        long_budget=float(long_budget),
        short_budget=float(short_budget),
        long_used=long_used,
        short_used=short_used,
        long_leftover=(long_budget - long_used).clip(lower=0.0),
        short_leftover=(short_budget - short_used).clip(lower=0.0),
    )


def rescale_budget(
    weights: pd.DataFrame,
    *,
    mode: str = "fixed",
    long_budget: float = 1.0,
    short_budget: float = 1.0,
) -> pd.DataFrame:
    """Apply explicit side budgets; flexible mode never scales a side upward."""
    return apply_budget(
        weights,
        policy=mode,
        long_budget=long_budget,
        short_budget=short_budget,
    ).weights


__all__ = [
    "BUDGET_POLICIES",
    "BudgetPolicyRegistry",
    "BudgetPolicySpec",
    "BudgetResult",
    "SideScales",
    "apply_budget",
    "budget_policy",
    "list_budget_policies",
    "register_budget_policy",
    "rescale_budget",
]
