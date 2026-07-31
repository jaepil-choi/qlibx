from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from echolon.signals import (
    ScoreVector,
    SignalEngine,
    SignalValidationError,
    assert_no_identity_literals,
    validate_signal_engine,
    validate_score_vector,
)


@dataclass(frozen=True)
class _View:
    date: dt.date


class _Panel:
    def __init__(self, dates: list[dt.date]) -> None:
        self.calendar = dates
        self.instruments = ["al", "cu"]

    def view(self, date: dt.date) -> _View:
        return _View(date=date)


class _DeterministicSignal(SignalEngine):
    signal_id = "det_v1"
    family = "tsmom"
    params = {"lookback": 252}
    data_requirements = {"bars": 252}

    def compute(self, view):
        return ScoreVector(
            signal_id=self.signal_id,
            family=self.family,
            date=view.date,
            scores={"al": 1.0, "cu": None},
        )


def test_score_vector_schema_and_validation_accept_none_for_missing_requirements():
    vector = ScoreVector(
        signal_id="carry_v1",
        family="carry",
        date=dt.date(2024, 1, 3),
        scores={"al": 2.5, "cu": None},
    )

    validate_score_vector(vector, expected_date=dt.date(2024, 1, 3), instruments=["al", "cu"])

    assert vector.schema == "scores/v1"


def test_score_validation_rejects_uncapped_scores_and_wrong_dates():
    vector = ScoreVector(
        signal_id="bad_v1",
        family="tsmom",
        date=dt.date(2024, 1, 4),
        scores={"al": 3.1},
    )

    with pytest.raises(SignalValidationError, match="date"):
        validate_score_vector(vector, expected_date=dt.date(2024, 1, 3), instruments=["al"])
    with pytest.raises(SignalValidationError, match="cap"):
        validate_score_vector(vector, expected_date=dt.date(2024, 1, 4), instruments=["al"])


def test_score_validation_requires_explicit_none_instead_of_missing_instrument():
    vector = ScoreVector(
        signal_id="carry_v1",
        family="carry",
        date=dt.date(2024, 1, 3),
        scores={"al": 1.0},
    )

    with pytest.raises(SignalValidationError, match="missing instruments"):
        validate_score_vector(vector, expected_date=dt.date(2024, 1, 3), instruments=["al", "cu"])


def test_compute_history_defaults_to_panel_view_loop():
    dates = [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    panel = _Panel(dates)
    signal = _DeterministicSignal()

    history = signal.compute_history(panel, dates)

    assert [row.date for row in history] == dates
    assert [row.scores for row in history] == [{"al": 1.0, "cu": None}, {"al": 1.0, "cu": None}]


def test_identity_literal_scan_rejects_registered_instrument_string_constants():
    class BadSignal(SignalEngine):
        signal_id = "bad_v1"
        family = "tsmom"
        params = {}
        data_requirements = {}
        forbidden = "al"

        def compute(self, view):
            return ScoreVector(
                signal_id=self.signal_id,
                family=self.family,
                date=view.date,
                scores={"al": 1.0},
            )

    with pytest.raises(SignalValidationError, match="instrument literal"):
        assert_no_identity_literals(BadSignal(), registered_instrument_ids={"al", "cu"})


def test_validate_signal_engine_rejects_nondeterministic_compute():
    class NondeterministicSignal(SignalEngine):
        signal_id = "nondet_v1"
        family = "tsmom"
        params = {}
        data_requirements = {}

        def __init__(self) -> None:
            self._count = 0

        def compute(self, view):
            self._count += 1
            return ScoreVector(
                signal_id=self.signal_id,
                family=self.family,
                date=view.date,
                scores={"al": float(self._count), "cu": None},
            )

    with pytest.raises(SignalValidationError, match="deterministic"):
        validate_signal_engine(
            NondeterministicSignal(),
            _View(dt.date(2024, 1, 3)),
            registered_instrument_ids={"rb", "hc"},
        )
