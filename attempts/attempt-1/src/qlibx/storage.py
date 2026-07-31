"""One door to everything a project has stored.

A finished qlibx project holds results in three places, and before this module a caller
had to know all three names, three import paths, and three ways to construct them -- one
of which took a file path while the other two took the project. "Where did my result go"
is one question, so it gets one answer:

    storage = ProjectStorage.from_project(project)
    storage.artifacts.load(artifact_id, run_id=run_id)
    storage.research.list_results()
    storage.runs(catalog_path).load_table(run_id, "orders")

The three remain separate implementations, because they are separate things: artifacts are
run-local and content-addressed, research is a staged publication protocol with an
append-only event log, and a run catalog is vendored Qlib storage this package only reads.
This is a front door, not a merge -- pointing at the three from one place is what was
missing, not one storage engine behind them.

The original imports keep working. Nothing here removes a way to reach a store.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from qlibx.artifacts import ArtifactStore
from qlibx.project import Project
from qlibx.research import ResearchCatalog

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from qlibx.run_catalog import RunCatalog


@dataclass(frozen=True, slots=True)
class ProjectStorage:
    """The three stores of one project, reached through one object."""

    project: Project
    artifacts: ArtifactStore
    research: ResearchCatalog

    @classmethod
    def from_project(cls, project: Project) -> ProjectStorage:
        return cls(
            project=project,
            artifacts=ArtifactStore.from_project(project),
            research=ResearchCatalog.from_project(project),
        )

    def runs(self, catalog_path: str | Path) -> RunCatalog:
        """Open a stored-run catalog for reading.

        Takes an explicit path because a run catalog is written by an execution, which
        chooses where it lives -- unlike artifacts and research, whose roots the project
        declares.

        The import is deferred so that opening a project's storage does not load the
        vendored Qlib run store. It does not save DuckDB: `research` imports that at
        module scope already, so the door costs DuckDB either way.
        """
        from qlibx.run_catalog import open_run_catalog

        return open_run_catalog(catalog_path)


__all__ = ["ProjectStorage"]
