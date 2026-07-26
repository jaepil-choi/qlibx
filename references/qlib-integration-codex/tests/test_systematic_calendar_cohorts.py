from __future__ import annotations

from qlib_extended.research.cohorts import _consensus_weight_schemes


def test_consensus_weight_schemes_are_bounded_and_sum_to_one() -> None:
    names = [
        "fy1__revision_only",
        "eps__revision_only",
        "fy1__underreaction",
        "eps__underreaction",
    ]
    turnovers = dict(zip(names, [60.0, 70.0, 80.0, 90.0], strict=True))

    schemes = _consensus_weight_schemes(names, turnovers)

    assert set(schemes) == {
        "equal_all",
        "core_revision_equal",
        "core80_satellite20",
        "inverse_turnover",
    }
    for weights in schemes.values():
        assert abs(sum(weights.values()) - 1.0) < 1e-12
        assert min(weights.values()) >= 0.0
