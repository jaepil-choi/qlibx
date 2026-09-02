"""`DataModel` lives in `vqapr.authoring` now; this is the engine-side name for it.

Two classes carried this name -- one here, one an author was told to subclass -- and the loader
accepted only this one, so a model written the way the strategy scaffold taught could not be run
at all (`docs/issues/036`, R5). There is one class. `vqapr.public.DataModel is
vqapr.authoring.DataModel`, and a test asserts it.
"""

from __future__ import annotations

from vqapr.authoring import DataModel

__all__ = ("DataModel",)
