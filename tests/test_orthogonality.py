from __future__ import annotations

import pandas as pd
import pytest

from qlibx.research import AlphaDescriptor, compare_alpha


def test_semantic_family_and_ticker_signal_comparison_are_separate() -> None:
    candidate = AlphaDescriptor("a", "reversal", ("return",), "close", "5d", ("rank",))
    reference = AlphaDescriptor("b", "reversal", ("return",), "close", "20d", ("rank",))
    date = pd.DatetimeIndex(["2025-01-01", "2025-01-02"])
    left = pd.DataFrame([[1.0, -1.0], [0.5, -0.5]], index=date, columns=["x", "y"])
    right = -left
    result = compare_alpha(
        candidate,
        reference,
        candidate_signal=left,
        reference_signal=right,
    )
    assert result.classification == "family_variation"
    assert result.signal_correlation == pytest.approx(-1.0)
    assert "holding" in result.missing_comparisons
    assert result.residual_ratio == pytest.approx(0.0)


def test_distinct_mechanism_is_not_inferred_from_pnl_correlation() -> None:
    candidate = AlphaDescriptor("a", "quality", ("fundamental",), "filing", "60d", ("zscore",))
    reference = AlphaDescriptor("b", "momentum", ("return",), "close", "20d", ("rank",))
    result = compare_alpha(candidate, reference)
    assert result.classification == "distinct_hypothesis"
    assert result.signal_correlation is None
    assert set(result.missing_comparisons) == {"signal", "holding", "incremental_residual"}
