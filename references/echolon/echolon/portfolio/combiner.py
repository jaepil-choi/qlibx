"""Score blending."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from echolon.signals import ScoreVector


class Combiner:
    """Blend signal scores with per-instrument weight renormalization."""

    def __init__(self, weights: Mapping[str, float]) -> None:
        if not weights:
            raise ValueError("blend weights must not be empty")
        total = sum(float(value) for value in weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError("blend weights must sum to 1.0")
        self.weights = {signal_id: float(weight) for signal_id, weight in weights.items()}

    def combine(self, vectors: Iterable[ScoreVector], *, instruments: Iterable[str]) -> dict[str, float]:
        by_signal = {vector.signal_id: vector for vector in vectors}
        blended: dict[str, float] = {}
        for instrument in instruments:
            numerator = 0.0
            denominator = 0.0
            for signal_id, weight in self.weights.items():
                vector = by_signal.get(signal_id)
                if vector is None:
                    continue
                score = vector.scores.get(instrument)
                if score is None:
                    continue
                numerator += weight * float(score)
                denominator += weight
            blended[instrument] = numerator / denominator if denominator else 0.0
        return blended

