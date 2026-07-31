"""Validation helpers for public signal engines."""
from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Iterable

from echolon.panel import PanelView

from .base import SignalEngine
from .models import ScoreVector

SCORE_CAP = 3.0


class SignalValidationError(ValueError):
    """Raised when a signal violates the public S2 contract."""


def validate_score_vector(
    vector: ScoreVector,
    *,
    expected_date,
    instruments: Iterable[str],
) -> None:
    """Validate score shape, date, instrument keys, and +/-3 cap."""
    if vector.date != expected_date:
        raise SignalValidationError(
            f"score vector date {vector.date} does not match expected date {expected_date}"
        )
    allowed = {instrument.lower() for instrument in instruments}
    unknown = set(vector.scores).difference(allowed)
    if unknown:
        raise SignalValidationError(f"score vector contains unknown instruments: {sorted(unknown)}")
    missing = allowed.difference(vector.scores)
    if missing:
        raise SignalValidationError(
            f"score vector missing instruments; use None when requirements are unmet: {sorted(missing)}"
        )
    for instrument, score in vector.scores.items():
        if instrument != instrument.lower():
            raise SignalValidationError(f"instrument id must be lowercase: {instrument}")
        if score is None:
            continue
        if abs(float(score)) > SCORE_CAP:
            raise SignalValidationError(
                f"score cap exceeded for {instrument}: {score} outside +/-{SCORE_CAP}"
            )


def assert_no_identity_literals(
    engine: SignalEngine,
    *,
    registered_instrument_ids: Iterable[str],
) -> None:
    """Reject signal classes containing string constants equal to instruments."""
    registered = {instrument.lower() for instrument in registered_instrument_ids}
    try:
        source = inspect.getsource(engine.__class__)
    except OSError as exc:
        raise SignalValidationError("cannot inspect signal source for identity literals") from exc
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in registered:
                raise SignalValidationError(
                    f"signal {engine.signal_id} contains instrument literal {node.value!r}"
                )


def validate_signal_engine(
    engine: SignalEngine,
    view: PanelView,
    *,
    registered_instrument_ids: Iterable[str],
) -> ScoreVector:
    """Validate source literals, score contract, and deterministic compute."""
    assert_no_identity_literals(engine, registered_instrument_ids=registered_instrument_ids)
    first = engine.compute(view)
    second = engine.compute(view)
    if first.model_dump(mode="json") != second.model_dump(mode="json"):
        raise SignalValidationError(f"signal {engine.signal_id} compute is not deterministic")
    validate_score_vector(
        first,
        expected_date=view.date,
        instruments=registered_instrument_ids,
    )
    return first
