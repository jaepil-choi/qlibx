import pytest

from echolon.portfolio.degradation import implementation_degradation


@pytest.mark.parametrize(
    ("research", "implementation", "expected_ratio"),
    [
        ({"net_sharpe": 1.25}, {"net_sharpe": 0.875}, 0.7),
        ({"net_sharpe": -0.5}, {"net_sharpe": -0.25}, 0.5),
    ],
)
def test_implementation_degradation_reports_ratio_without_judging(
    research: dict[str, float],
    implementation: dict[str, float],
    expected_ratio: float,
) -> None:
    assert implementation_degradation(research, implementation) == {
        "research_net_sharpe": research["net_sharpe"],
        "implementation_net_sharpe": implementation["net_sharpe"],
        "ratio": pytest.approx(expected_ratio),
        "bound": None,
    }
