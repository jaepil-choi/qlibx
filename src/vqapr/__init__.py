"""vqapr: author economic decisions, not object graphs.

The supported lifecycle is one facade and its declarations:

    import vqapr

    project = vqapr.open(root)          # read-only open; creates nothing
    receipt = project.register(...)     # the only external mutation door

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
