"""두 showcase 전략: 데이터 조회와 weight 산출만 담당한다."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from qlibx import (
    BudgetMode,
    ComponentRequirement,
    DecisionAction,
    RowsLookback,
    StrategyDraft,
    WeightEntry,
)


def _trailing_returns(
    frame: pd.DataFrame,
    *,
    value_column: str,
    instruments: tuple[str, ...],
    expected_rows: int,
) -> dict[str, float]:
    """각 종목의 window 첫 가격과 마지막 가격으로 수익률을 계산한다."""

    observed = {str(value) for value in frame["instrument"].unique()}
    if observed != set(instruments):
        raise ValueError(
            f"declared universe and observed instruments differ: {sorted(observed)}"
        )

    returns: dict[str, float] = {}
    for instrument, group in frame.groupby("instrument", sort=True):
        # ObservationStore가 오름차순으로 돌려주지만, 전략의 경제적 의미를 코드에 명시한다.
        ordered = group.sort_values(
            ["observation_time", "available_at"], kind="mergesort"
        )
        if len(ordered) != expected_rows:
            raise ValueError(
                f"{instrument} requires exactly {expected_rows} visible observations, "
                f"got {len(ordered)}"
            )
        first = float(ordered.iloc[0][value_column])
        last = float(ordered.iloc[-1][value_column])
        if first <= 0 or last <= 0:
            raise ValueError(f"{instrument} contains a non-positive price")
        returns[str(instrument)] = last / first - 1.0
    return returns


class PeerMomentumLongShortStrategy:
    """같은 peer group의 다른 종목 momentum으로 signed alpha weight를 만든다."""

    strategy_id = "showcase.peer-momentum-long-short"

    def __init__(
        self,
        *,
        dataset_id: str,
        peer_groups: Mapping[str, tuple[str, ...]],
        lookback_sessions: int = 20,
    ) -> None:
        self._dataset_id = dataset_id
        self._peer_groups = dict(peer_groups)
        self._lookback_sessions = lookback_sessions
        flattened = tuple(
            instrument
            for group in self._peer_groups.values()
            for instrument in group
        )
        if len(flattened) != len(set(flattened)):
            raise ValueError("an instrument may belong to only one peer group")
        if any(len(group) < 2 for group in self._peer_groups.values()):
            raise ValueError("peer momentum requires at least two instruments per group")
        self._instruments = tuple(sorted(flattened))

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="peer_momentum.trailing_close",
                semantic_role="research_close",
                dataset_id=self._dataset_id,
                # 20-session 수익률은 시작 가격까지 포함해 21개 관측이 필요하다.
                lookback=RowsLookback(rows=self._lookback_sessions + 1),
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        # Strategy는 등록 파일을 직접 열지 않고, 선언한 semantic role만 PIT view로 읽는다.
        history = view.history(  # type: ignore[attr-defined]
            "research_close", instruments=self._instruments
        )
        own_returns = _trailing_returns(
            history,
            value_column="research_close",
            instruments=self._instruments,
            expected_rows=self._lookback_sessions + 1,
        )

        peer_signal: dict[str, float] = {}
        for group in self._peer_groups.values():
            for instrument in group:
                peers = [own_returns[peer] for peer in group if peer != instrument]
                peer_signal[instrument] = sum(peers) / len(peers)

        # 횡단면 평균을 제거해 net 0으로 만들고, 절댓값 합을 1로 맞춰 gross 100%로 만든다.
        mean_signal = sum(peer_signal.values()) / len(peer_signal)
        centered = {
            instrument: signal - mean_signal
            for instrument, signal in peer_signal.items()
        }
        gross = sum(abs(value) for value in centered.values())
        if gross == 0:
            raise ValueError("peer momentum cross-section has zero dispersion")
        weights = {
            instrument: value / gross for instrument, value in centered.items()
        }
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=instrument, weight=weights[instrument])
                for instrument in sorted(weights)
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=(
                "peer signal = mean trailing return of the other names in its group",
                "cross-sectional demean and unit-gross normalization",
            ),
        )


class FiveSessionTopTenStrategy:
    """5-session 수익률 상위 10종목을 10%씩 보유하는 KRX long-only 전략."""

    strategy_id = "showcase.five-session-top-ten"

    def __init__(
        self,
        *,
        dataset_id: str,
        instruments: tuple[str, ...],
    ) -> None:
        if len(instruments) < 10:
            raise ValueError("top-10 strategy requires at least ten instruments")
        self._dataset_id = dataset_id
        self._instruments = tuple(sorted(instruments))

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="top_ten.five_session_close",
                semantic_role="research_close",
                dataset_id=self._dataset_id,
                # t-5 종가와 t 종가가 모두 있어야 하므로 정확히 6개 row를 요청한다.
                lookback=RowsLookback(rows=6),
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        history = view.history(  # type: ignore[attr-defined]
            "research_close", instruments=self._instruments
        )
        trailing = _trailing_returns(
            history,
            value_column="research_close",
            instruments=self._instruments,
            expected_rows=6,
        )
        # 동일 수익률이면 instrument ID 오름차순을 tie-break로 사용해 결과를 결정적으로 만든다.
        ranked = sorted(trailing, key=lambda item: (-trailing[item], item))
        selected = tuple(ranked[:10])
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=instrument, weight=0.1)
                for instrument in sorted(selected)
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            diagnostics=(
                "ranked by trailing five-session close return",
                "top ten receive equal 10 percent target weights",
            ),
        )
