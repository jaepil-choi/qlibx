"""`StrategyModel` lives in `vqapr.authoring` now; this is the engine-side name for it.

Two classes carried this name -- one here, one an author was told to subclass -- and an adapter
in `_internal/strategy_bridge.py` translated between them on every callback (`docs/issues/036`).
There is one class. `vqapr.public.StrategyModel is vqapr.authoring.StrategyModel`, and a test
asserts it.
"""

from __future__ import annotations

from vqapr.authoring import StrategyModel

__all__ = ("StrategyModel",)
