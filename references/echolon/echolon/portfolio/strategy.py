"""Pure portfolio strategy composition."""
from __future__ import annotations

from collections.abc import Mapping

from echolon.panel import PanelView
from echolon.signals import SignalEngine, validate_score_vector

from .combiner import Combiner
from .constructor import Constructor, ConstructorConfig
from .models import BookState, RebalanceRecord, TargetBook


class PortfolioStrategy:
    """Compose SignalEngine, Combiner, and Constructor into target lots."""

    def __init__(
        self,
        engines: list[SignalEngine],
        blend: Mapping[str, float],
        constructor_cfg: ConstructorConfig,
    ) -> None:
        self.engines = list(engines)
        self.combiner = Combiner(blend)
        self.constructor = Constructor(constructor_cfg)

    def rebalance(self, view: PanelView, book: BookState) -> tuple[TargetBook, RebalanceRecord]:
        vectors = [engine.compute(view) for engine in self.engines]
        instruments = (
            list(view.instruments)
            if hasattr(view, "instruments")
            else _instruments_from_vectors(vectors)
        )
        for vector in vectors:
            validate_score_vector(vector, expected_date=view.date, instruments=instruments)
        blended = self.combiner.combine(vectors, instruments=instruments)
        raw_scores = {
            instrument: {
                vector.signal_id: vector.scores[instrument]
                for vector in vectors
            }
            for instrument in instruments
        }
        return self.constructor.construct(
            view=view,
            book=book,
            blended_scores=blended,
            raw_scores=raw_scores,
        )


def _instruments_from_vectors(vectors) -> list[str]:
    instruments: list[str] = []
    seen: set[str] = set()
    for vector in vectors:
        for instrument in vector.scores:
            if instrument not in seen:
                instruments.append(instrument)
                seen.add(instrument)
    return instruments
