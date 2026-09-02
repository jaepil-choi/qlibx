"""`Model` lives in `vqapr.authoring` now; this is the engine-side name for it.

It was defined here while an authoring `DataModel` and `StrategyModel` were defined without it,
which is why the two authored kinds shared no ancestor and why a class written against the
author's module could not be run (`docs/issues/036`). The base is the author's, so it lives on
the author's surface. Every internal path that imported it from here keeps working, and names the
same object.
"""

from __future__ import annotations

from vqapr.authoring import Model

__all__ = ("Model",)
