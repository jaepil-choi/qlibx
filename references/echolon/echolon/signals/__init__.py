"""Public signal interfaces and validation helpers."""
from .base import SignalEngine
from .models import ScoreVector
from .validation import (
    SignalValidationError,
    assert_no_identity_literals,
    validate_score_vector,
    validate_signal_engine,
)

__all__ = [
    "ScoreVector",
    "SignalEngine",
    "SignalValidationError",
    "assert_no_identity_literals",
    "validate_score_vector",
    "validate_signal_engine",
]

