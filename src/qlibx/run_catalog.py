"""Read access to the stored-run catalog, independent of the execution engine.

Reporting reads finished runs; it never executes one. Routing that read through
``qlibx.execution`` made the whole Qlib runtime a transitive dependency of a module the
PRD defines as strictly non-computational. This port is the seam: it owns the vendored
catalog type so a reader and a runner can each depend on what they actually use.
"""

from __future__ import annotations

from pathlib import Path

from ._vendor.qlib_engine.store import ParentLink, RunCatalog


def open_run_catalog(path: str | Path) -> RunCatalog:
    """Open a verified, immutable-artifact run catalog."""
    return RunCatalog.open(path)


__all__ = ["ParentLink", "RunCatalog", "open_run_catalog"]
