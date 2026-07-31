"""Registry surfaces — frequency-based indicator routing + pluggable regime classifiers."""
from echolon.indicators.registry.regime_classifiers import (
 register_regime_classifier,
 register_regime_optimizer,
 get_regime_classifier,
 get_regime_optimizer,
 list_classifiers,
 list_optimizers,
 is_registered_classifier,
 KNOWN_REGIME_COLUMNS,
)

__all__ = [
 "register_regime_classifier",
 "register_regime_optimizer",
 "get_regime_classifier",
 "get_regime_optimizer",
 "list_classifiers",
 "list_optimizers",
 "is_registered_classifier",
 "KNOWN_REGIME_COLUMNS",
]
