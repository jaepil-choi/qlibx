"""vqapr: author economic decisions, not object graphs.

**The documented surface is the CLI**, and `vqapr.public` is the supported implementation surface
it stands on. A strategy, datamodel, exchange or constraint is Python; declaring and installing one
is `vqapr register`; proving a run is ready is `vqapr check`; running it is `vqapr run`.

`vqapr.open()` below returns a `Project` facade that **no shipped command calls**. It and the
modules behind it are unshipped and frozen: no new callers, no growth, and no deletion either --
removing them is a separately gated decision. The ruling, the measurement behind it, and what a
future deletion would have to satisfy are in `docs/design/agent-first-surface.md` under
"The ruling -- 2026-08-28". Read that before building on this entry point.

Capability modules are imported lazily so that `import vqapr` stays cheap and so that a
capability that is still being built cannot break the package import for every caller.
"""

from __future__ import annotations

__all__ = (
    "authoring",
    "materialization",
    "open",
    "project",
    "simulation",
)

_CAPABILITIES = frozenset({"authoring", "materialization", "project", "simulation"})


def open(root):
    """Open a project at `root` WITHOUT creating anything.

    The import is deferred into the call rather than done at module scope so that
    `import vqapr.analysis.signal` does not drag the project/runtime layers in behind it.
    `tests/boundaries/test_capability_absence.py` enforces exactly that: a leaf capability
    must stay importable without reaching the layers it does not depend on.
    """
    from vqapr.project import open as _open

    return _open(root)


def __getattr__(name: str):
    """Resolve capability modules on first attribute access.

    Kept lazy for the same boundary reason as `open`, and because the capability set is
    still being migrated: an eager import would make one unfinished module a hard failure
    for `import vqapr` itself.
    """
    if name in _CAPABILITIES:
        import importlib

        module = importlib.import_module(f"vqapr.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'vqapr' has no attribute {name!r}")
