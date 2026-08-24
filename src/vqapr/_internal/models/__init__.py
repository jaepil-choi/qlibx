"""Private agent-first runtime adapters over `vqapr.authoring`.

This package holds the fresh-instance invocation boundary that turns one immutable
`vqapr.authoring.DataModel`/`StrategyModel` declaration plus an injected PIT observation
resolver into a validated, private prepared result. It is not part of the public API: a
caller outside `vqapr` must never import from here.
"""

from __future__ import annotations
