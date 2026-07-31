"""Processor-level tests for the optional ``{classifier}_confidence`` column.

The indicator processor emits a per-bar confidence companion column for any
registered classifier that opts in via ``emits_confidence = True``. The
confidence is the posterior probability of the ASSIGNED label
(``proba[label]`` per bar) — never ``max(proba)`` — so it stays consistent
with the (unchanged) label column even when the labeller (e.g. an HMM using
Viterbi) disagrees with the per-bar argmax of the posterior.

Echolon ships zero classifiers; these tests register paradigm-blind stubs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from echolon.indicators.engine.processor import _compute_indicators_for_contract


class _Ctx:
    """Minimal TradingContext stub — the dispatch path only reads is_intraday."""

    is_intraday = False


def _make_df(n: int = 6) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": np.linspace(1.0, 2.0, n),
            "high": np.linspace(1.1, 2.1, n),
            "low": np.linspace(0.9, 1.9, n),
            "close": np.linspace(1.0, 2.0, n),
            "volume": np.arange(n, dtype=float) + 1.0,
        },
        index=idx,
    )


class _ConfidenceStub:
    """Opt-in classifier: label = argmax-ish; proba columns = label strings."""

    name = "stub_confidence"
    label_map = {0: "calm", 1: "storm"}
    emits_confidence = True

    def __init__(self, labels, proba):
        self._labels = np.asarray(labels)
        self._proba = proba

    def fit_classify(self, df, params):
        return pd.Series(self._labels, index=df.index, name=self.name)

    def fit_classify_proba(self, df, params):
        return pd.DataFrame(self._proba, index=df.index, columns=["calm", "storm"])


class _NoConfidenceStub:
    """Rule-based-style classifier: emits a label only, NO confidence."""

    name = "stub_plain"
    label_map = {0: "calm", 1: "storm"}
    emits_confidence = False

    def fit_classify(self, df, params):
        return pd.Series(
            np.zeros(len(df), dtype=int), index=df.index, name=self.name
        )

    def fit_classify_proba(self, df, params):  # pragma: no cover - must NOT be called
        raise AssertionError(
            "fit_classify_proba must not be called when emits_confidence is False"
        )


def _register(classifier):
    from echolon.indicators.registry import register_regime_classifier

    register_regime_classifier(classifier)


def test_confidence_column_emitted_as_proba_of_assigned_label():
    df = _make_df(5)
    labels = [0, 1, 0, 1, 0]
    # proba[label] per bar = [0.7, 0.8, 0.55, 0.9, 0.6]
    proba = np.array(
        [
            [0.7, 0.3],
            [0.2, 0.8],
            [0.55, 0.45],
            [0.1, 0.9],
            [0.6, 0.4],
        ]
    )
    _register(_ConfidenceStub(labels, proba))

    results = _compute_indicators_for_contract(
        df,
        indicator_list={"stub_confidence": {}},
        ctx=_Ctx(),
        regime_params={},
    )

    # Label column unchanged.
    assert "stub_confidence" in results
    np.testing.assert_array_equal(results["stub_confidence"], np.asarray(labels))

    # Confidence column present and equal to proba[label] per bar.
    assert "stub_confidence_confidence" in results
    expected = np.array([0.7, 0.8, 0.55, 0.9, 0.6])
    np.testing.assert_allclose(results["stub_confidence_confidence"], expected)
    # And it is in [0, 1].
    conf = results["stub_confidence_confidence"]
    assert conf.min() >= 0.0 and conf.max() <= 1.0


def test_confidence_is_proba_of_label_not_max_when_they_differ():
    """Viterbi-vs-argmax case: the label disagrees with the posterior argmax.

    Confidence must follow the STORED label, never ``max(proba)``.
    """
    df = _make_df(3)
    labels = [0, 0, 1]  # bar 0/1 labelled "calm" though "storm" has higher proba
    proba = np.array(
        [
            [0.4, 0.6],  # argmax = storm(1), but label = calm(0) -> conf 0.4
            [0.3, 0.7],  # argmax = storm(1), but label = calm(0) -> conf 0.3
            [0.45, 0.55],  # argmax = storm(1), label = storm(1) -> conf 0.55
        ]
    )
    _register(_ConfidenceStub(labels, proba))

    results = _compute_indicators_for_contract(
        df,
        indicator_list={"stub_confidence": {}},
        ctx=_Ctx(),
        regime_params={},
    )

    conf = results["stub_confidence_confidence"]
    np.testing.assert_allclose(conf, [0.4, 0.3, 0.55])
    # Explicitly NOT max(proba) for the first two bars.
    assert conf[0] != 0.6 and conf[1] != 0.7


def test_no_confidence_column_for_non_emitting_classifier():
    df = _make_df(4)
    _register(_NoConfidenceStub())

    results = _compute_indicators_for_contract(
        df,
        indicator_list={"stub_plain": {}},
        ctx=_Ctx(),
        regime_params={},
    )

    assert "stub_plain" in results
    assert "stub_plain_confidence" not in results
