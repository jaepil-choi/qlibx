"""vqapr: author economic decisions, not object graphs.

**The documented surface is the CLI**, and `vqapr.public` is the supported implementation surface
it stands on. A strategy, datamodel, exchange or constraint is Python; declaring and installing one
is `vqapr register`; proving a run is ready is `vqapr check`; running it is `vqapr run`.

`vqapr.open()` and the `Project` facade behind it are **gone**. They were the destination of an
earlier design in which `vqapr.public` was the legacy layer to be deleted; a PEP 669 trace of a
complete CLI journey inverted that finding — `project.py`, `simulation.py`, `materialization.py`,
`venues.py` and the `_internal` bridges below them ran **zero** lines under the shipped commands
and were exercised only by the tests written for them. `docs/design/agent-first-surface.md`
records the measurement and the ruling; the deletion itself is `docs/implementations/124`.

`vqapr.authoring` survives that deletion and is not part of it: a registered StrategyModel may be
written against it, and `component/loading.py` adapts it onto the engine contract at load time.

The capability import stays lazy so that `import vqapr` stays cheap, and so that a leaf capability
remains importable without dragging heavier layers in behind it —
`tests/boundaries/test_capability_absence.py` enforces exactly that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # The lazy `__getattr__` below is the runtime door; this is the same name for the checker.
    from vqapr import authoring

__all__ = ("authoring",)

_CAPABILITIES = frozenset({"authoring"})


def __getattr__(name: str):
    """Resolve capability modules on first attribute access."""
    if name in _CAPABILITIES:
        import importlib

        module = importlib.import_module(f"vqapr.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'vqapr' has no attribute {name!r}")
