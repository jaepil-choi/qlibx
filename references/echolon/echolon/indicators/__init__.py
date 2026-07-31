"""
Indicators Module
=================

Technical indicator calculation engine.

Public surfaces:

- ``catalog`` — indicator metadata + registration table (paradigm-blind).
- ``register_regime_classifier`` / ``register_regime_optimizer`` — register
 custom classifiers/optimizers. Echolon ships **zero built-in classifiers**;
 host code registers its own (TRS rule-based, HMM, Carry, etc.).
- ``get_regime_classifier`` / ``get_regime_optimizer`` — registry lookup.
- ``list_classifiers`` / ``list_optimizers`` — introspection.

See :mod:`echolon.indicators.protocols` for the Protocol definitions.

Typical usage from host code::

 from echolon.indicators import register_regime_classifier
 register_regime_classifier(MyTRSClassifier()) # at session start

The classifier + optimizer are then accessible by name via
``echolon.indicators.get_regime_classifier("...")`` and
``echolon.indicators.get_regime_optimizer("...")`` from anywhere
in the indicator pipeline.
"""
from echolon.indicators import catalog

# Classifier registry — extension point for paradigm-specific machinery.
from echolon.indicators.registry import (
 register_regime_classifier,
 register_regime_optimizer,
 get_regime_classifier,
 get_regime_optimizer,
 list_classifiers,
 list_optimizers,
)

__all__ = [
 "catalog",
 "register_regime_classifier",
 "register_regime_optimizer",
 "get_regime_classifier",
 "get_regime_optimizer",
 "list_classifiers",
 "list_optimizers",
]
