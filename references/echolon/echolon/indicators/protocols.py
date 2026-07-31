"""Pluggable interfaces for paradigm-specific machinery.

Echolon ships **no built-in regime classifiers**. Host code registers its
own classifiers — TRS rule-based, HMM, GMM, Carry term-structure, custom
domain — via the registry in ``echolon.indicators.registry``.

Echolon does not depend on any consumer; it only knows about names that
have been registered with it. Any external package can plug in custom
classifiers / optimizers without modifying echolon source.

See :mod:`echolon.indicators.registry.regime_classifiers` for the
registry API.
"""
from __future__ import annotations
from typing import Protocol, Dict, Any, runtime_checkable

import pandas as pd


@runtime_checkable
class RegimeClassifier(Protocol):
    """A pluggable regime classifier.

    Implementations classify each row of an OHLCV-shaped DataFrame and
    produce a numeric Series of regime labels aligned to ``df.index``.

    The Protocol is paradigm-blind — TRS uses a 4-state rule-based
    classifier, but other paradigms may use HMM (probabilistic state
    inference), GMM (Gaussian Mixture), or custom domain logic. The
    registry treats them uniformly.

    Required attributes:
        name: Stable string identifier — registered name in the classifier
            registry. Convention: lowercase, snake_case (e.g.,
            ``"market_regime"``, ``"hmm_3state"``, ``"carry_term_structure"``).
        label_map: Numeric → string label map. Used by analyzers and
            display layers to render integer regime states as
            human-readable labels.

    Required methods:
        fit_classify(df, params): Compute the regime time-series.
    """

    name: str
    label_map: Dict[int, str]

    def fit_classify(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
    ) -> pd.Series:
        """Classify each row of ``df``.

        Args:
            df: OHLCV-shaped DataFrame (typically with columns
                ``open / high / low / close / volume`` and a
                DatetimeIndex). Implementations may consume only a subset.
            params: Classifier-specific hyperparameter dict. The TRS
                rule-based classifier accepts
                ``{adx_period, adx_threshold, vol_window, vol_threshold,
                ...}``; an HMM classifier might accept
                ``{n_states, n_iter, covariance_type, ...}``.

        Returns:
            Numeric Series aligned to ``df.index`` whose values are
            keys of ``self.label_map``.
        """
        ...


@runtime_checkable
class RegimeClassifierOptimizer(Protocol):
    """A pluggable hyperparameter optimizer for a :class:`RegimeClassifier`.

    Echolon does NOT ship optimizers as part of its public API. Host code
    registers its own optimizer (e.g. an Optuna-driven search over a
    rule-based classifier's parameter space) via this Protocol.

    Required attributes:
        classifier_name: Name of the :class:`RegimeClassifier` this
            optimizer tunes. The registry pairs them by this name —
            ``register_regime_optimizer(opt)`` overwrites any previous
            optimizer for the same classifier.

    Required methods:
        optimize(df, n_trials, **kwargs): Find the best hyperparameter
            dict for ``self.classifier_name``'s classifier on ``df``.
    """

    classifier_name: str

    def optimize(
        self,
        df: pd.DataFrame,
        n_trials: int = 100,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return optimal params dict accepted by
        ``RegimeClassifier.fit_classify``.

        Args:
            df: OHLCV-shaped DataFrame to optimize against.
            n_trials: Number of optimization trials.
            **kwargs: Optimizer-specific configuration passed through.

        Returns:
            Hyperparameter dict ready to feed into
            ``RegimeClassifier.fit_classify``.
        """
        ...
