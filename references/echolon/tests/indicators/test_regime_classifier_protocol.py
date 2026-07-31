"""Protocol/registry mechanics tests for regime classifiers.

The ``RegimeClassifier`` Protocol is the extension point for paradigm-
specific regime machinery. Echolon ships ZERO built-in classifiers; host
code registers its own (rule-based, HMM, GMM, Carry, etc.) through the
registry.

These tests verify the **paradigm-blind** Protocol shape + registry
mechanics. Classifier-specific conformance tests are the responsibility
of whoever ships the classifier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from echolon.indicators.protocols import (
    RegimeClassifier,
    RegimeClassifierOptimizer,
)


# ---------------------------------------------------------------------------
# Empty-by-default contract
# ---------------------------------------------------------------------------


def test_unregistered_classifier_raises_helpful_error():
    from echolon.indicators.registry import get_regime_classifier
    with pytest.raises(KeyError, match="No regime classifier registered"):
        get_regime_classifier("nonexistent_classifier")


def test_unregistered_optimizer_raises_helpful_error():
    from echolon.indicators.registry import get_regime_optimizer
    # Use a name that's guaranteed not to be registered
    with pytest.raises(KeyError, match="No regime optimizer registered"):
        get_regime_optimizer("definitely_not_registered_optimizer")


# ---------------------------------------------------------------------------
# Custom-classifier registration smoke (paradigm-blind tests with stubs)
# ---------------------------------------------------------------------------


class _DummyHMMClassifier:
    """Minimal Protocol-conforming classifier for testing."""

    name = "dummy_hmm"
    label_map = {0: "state_0", 1: "state_1"}

    def fit_classify(self, df, params):
        return pd.Series(np.zeros(len(df), dtype=int), index=df.index, name="dummy_hmm")


def test_dummy_classifier_implements_protocol():
    """A minimal stub satisfies the Protocol — the contract is small."""
    assert isinstance(_DummyHMMClassifier(), RegimeClassifier)


def test_custom_classifier_registers_and_dispatches():
    from echolon.indicators.registry import (
        register_regime_classifier,
        get_regime_classifier,
        list_classifiers,
    )
    register_regime_classifier(_DummyHMMClassifier())
    assert "dummy_hmm" in list_classifiers()
    classifier = get_regime_classifier("dummy_hmm")
    df = pd.DataFrame({"close": [100, 101, 102]}, index=pd.date_range("2024-01-01", periods=3))
    result = classifier.fit_classify(df, {})
    assert len(result) == 3
    assert (result == 0).all()


def test_re_registering_classifier_replaces_existing():
    from echolon.indicators.registry import (
        register_regime_classifier,
        get_regime_classifier,
        list_classifiers,
    )

    class _V1:
        name = "replaceable"
        label_map = {0: "v1"}
        def fit_classify(self, df, params):
            return pd.Series([0] * len(df), index=df.index)

    class _V2:
        name = "replaceable"
        label_map = {0: "v2"}
        def fit_classify(self, df, params):
            return pd.Series([1] * len(df), index=df.index)

    register_regime_classifier(_V1())
    register_regime_classifier(_V2())
    assert get_regime_classifier("replaceable").label_map == {0: "v2"}
    # Still only one entry in the list
    assert list_classifiers().count("replaceable") == 1


# ---------------------------------------------------------------------------
# Custom-optimizer registration smoke
# ---------------------------------------------------------------------------


class _DummyOptimizer:
    """Minimal Protocol-conforming optimizer for testing."""

    classifier_name = "dummy_hmm"

    def optimize(self, df, n_trials=100, **kwargs):
        return {"n_states": 2}


def test_dummy_optimizer_implements_protocol():
    assert isinstance(_DummyOptimizer(), RegimeClassifierOptimizer)


def test_custom_optimizer_registers():
    from echolon.indicators.registry import (
        register_regime_optimizer,
        get_regime_optimizer,
        list_optimizers,
    )
    register_regime_optimizer(_DummyOptimizer())
    assert "dummy_hmm" in list_optimizers()
    opt = get_regime_optimizer("dummy_hmm")
    assert opt.classifier_name == "dummy_hmm"
    df = pd.DataFrame({"close": [100, 101]}, index=pd.date_range("2024-01-01", periods=2))
    params = opt.optimize(df, n_trials=10)
    assert params == {"n_states": 2}
