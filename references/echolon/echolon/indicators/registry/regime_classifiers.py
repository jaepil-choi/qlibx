"""Registry for pluggable regime classifiers + optimizers.

Single-process, thread-safe. Host code registers classifiers at session
startup; echolon's pipeline looks them up by name at runtime.

Echolon does NOT depend on any consumer. Registration is the only direction
of dependency — host code calls into echolon's registry, never vice-versa.

See :mod:`echolon.indicators.protocols` for the Protocol definitions.
"""
from __future__ import annotations
from typing import Dict, List
import threading

from echolon.indicators.protocols import (
    RegimeClassifier, RegimeClassifierOptimizer,
)


# Canonical regime/session-classifier *column* names that echolon knows
# statically. The classifier IMPLEMENTATIONS are host-registered at runtime via
# ``register_regime_classifier`` (and are therefore ABSENT in a bare process —
# e.g. the stdio MCP validator), but the column NAMES are stable echolon
# vocabulary. Validators consult this set so they agree with the engine even
# when the runtime registry is empty: otherwise a correctly-declared
# ``market_regime`` is rejected as a false-positive "unknown indicator"
# (IND-004) in the MCP validator process. (component_smoke._SYSTEM_INDICATORS is
# a superset that also lists the always-available temporal columns; this set is
# only the must-declare-when-used classifier columns.)
KNOWN_REGIME_COLUMNS = frozenset({
    "market_regime", "session_phase", "session_phase_agg",
})


_LOCK = threading.RLock()
_CLASSIFIERS: Dict[str, RegimeClassifier] = {}
_OPTIMIZERS: Dict[str, RegimeClassifierOptimizer] = {}


def register_regime_classifier(classifier: RegimeClassifier) -> None:
    """Register (or replace) a classifier under its ``name`` attribute.

    Re-registering with the same name silently replaces the previous entry —
    convenient for testing and for hot-reloading classifier implementations.

    Args:
        classifier: Object conforming to :class:`RegimeClassifier` Protocol.
    """
    with _LOCK:
        _CLASSIFIERS[classifier.name] = classifier


def register_regime_optimizer(optimizer: RegimeClassifierOptimizer) -> None:
    """Register (or replace) an optimizer under its ``classifier_name`` attribute.

    Pairs with a classifier of the same name; one optimizer per classifier.

    Args:
        optimizer: Object conforming to :class:`RegimeClassifierOptimizer`.
    """
    with _LOCK:
        _OPTIMIZERS[optimizer.classifier_name] = optimizer


def get_regime_classifier(name: str) -> RegimeClassifier:
    """Look up a registered classifier. Raises ``KeyError`` if absent.

    Args:
        name: Classifier name to look up.

    Returns:
        The registered :class:`RegimeClassifier`.

    Raises:
        KeyError: If no classifier is registered under ``name``. The error
            message lists currently-registered classifier names.
    """
    with _LOCK:
        if name not in _CLASSIFIERS:
            registered = sorted(_CLASSIFIERS.keys())
            raise KeyError(
                f"No regime classifier registered under name={name!r}. "
                f"Registered: {registered}. "
                f"To add custom classifiers, call register_regime_classifier(...) "
                f"before invoking the indicator pipeline."
            )
        return _CLASSIFIERS[name]


def get_regime_optimizer(classifier_name: str) -> RegimeClassifierOptimizer:
    """Look up a registered optimizer for a classifier. Raises ``KeyError`` if absent.

    Args:
        classifier_name: Name of the classifier whose optimizer to look up.

    Returns:
        The registered :class:`RegimeClassifierOptimizer`.

    Raises:
        KeyError: If no optimizer is registered for ``classifier_name``. The
            error message lists currently-registered optimizer names.
    """
    with _LOCK:
        if classifier_name not in _OPTIMIZERS:
            registered = sorted(_OPTIMIZERS.keys())
            raise KeyError(
                f"No regime optimizer registered for classifier={classifier_name!r}. "
                f"Registered optimizers: {registered}. "
                f"Register an optimizer via register_regime_optimizer(...) "
                f"before invoking the indicator pipeline."
            )
        return _OPTIMIZERS[classifier_name]


def list_classifiers() -> List[str]:
    """Return sorted names of all registered classifiers."""
    with _LOCK:
        return sorted(_CLASSIFIERS.keys())


def list_optimizers() -> List[str]:
    """Return sorted classifier-names of all registered optimizers."""
    with _LOCK:
        return sorted(_OPTIMIZERS.keys())


def is_registered_classifier(name: str) -> bool:
    """Return True if ``name`` matches a registered classifier (case-insensitive).

    Used by the indicator pipeline to decide whether to dispatch via the
    classifier registry or fall through to the static ``indicator_mapping``.
    """
    with _LOCK:
        lower = name.lower()
        return any(k.lower() == lower for k in _CLASSIFIERS.keys())
