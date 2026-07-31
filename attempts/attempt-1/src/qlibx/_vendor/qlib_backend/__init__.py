"""Lazy exports for Qlib execution and optional research capabilities."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "ParquetArtifactStore",
    "ParquetResearchCatalog",
    "QlibClosedLoopBackend",
    "QlibMLResearchPipeline",
    "ResearchGraph",
    "ResearchGraphExecutor",
]


_EXPORTS = {
    "ParquetArtifactStore": (".artifacts", "ParquetArtifactStore"),
    "ParquetResearchCatalog": (".research_graph", "ParquetResearchCatalog"),
    "QlibClosedLoopBackend": (".backend", "QlibClosedLoopBackend"),
    "QlibMLResearchPipeline": (".ml_research", "QlibMLResearchPipeline"),
    "ResearchGraph": (".research_graph", "ResearchGraph"),
    "ResearchGraphExecutor": (".research_graph", "ResearchGraphExecutor"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(importlib.import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
