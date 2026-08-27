"""The single definition of a run spec's `store` block.

AC-R2 says the run spec carries `period`/`account`/`venue`/`execution`/`store`, and that `store`
has exactly `root` and `tables`. AC-P3 then says something that looks like a second rule -- an
empty `tables` leaves a run record and no dataset, a non-empty one makes each named table a
dataset -- but is really an observable consequence of the first.

Writing it twice is what makes it two rules. This module is the one place the keys are named, and
AC-P3's test imports `StoreSpec` rather than restating its literals, so a divergence between the
definition and the assertion is a type error rather than a drift nobody notices.

`store.root` exists because `WORKSPACE_DIRECTORY` was hardcoded (`workspace.py:47`). The heavy
artifacts a run produces -- roughly 500MB for the factor testbed -- were forced to live inside the
same `.vqapr/` directory as the catalog, which is a small file that wants to be backed up and
version-controlled. They are different kinds of thing with different lifetimes, and one path
forced them together.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

STORE_KEYS = ("root", "tables")
"""Exactly the keys `store` may carry.

Named once, here. A second list somewhere else is how `root` becomes optional in one reader and
required in another, and neither reader is wrong on its own.
"""


@dataclass(frozen=True, slots=True)
class StoreSpec:
    """Where a run's heavy artifacts go, and which of its tables become datasets.

    `tables` defaults to empty on purpose: it is the qlib `task.record` opt-in shape, where
    recording everything by default would make every run pay to publish tables nobody asked for.
    An empty list is a complete answer -- it means the run leaves a record and no dataset.
    """

    root: Path | None = None
    tables: tuple[str, ...] = ()

    @classmethod
    def of(cls, declared: object, *, base: Path) -> StoreSpec:
        """Read the `store` block, resolving a relative root against the spec's own directory.

        A relative path resolves against the spec, not the process's working directory. The
        alternative makes the same spec mean different things depending on where it was run from,
        which is the class of bug that only appears once someone runs it from somewhere else.
        """
        if declared is None:
            return cls()
        if not isinstance(declared, Mapping):
            raise TypeError(f"store must be a mapping of {', '.join(STORE_KEYS)}")

        unknown = sorted(set(declared) - set(STORE_KEYS))
        if unknown:
            raise ValueError(
                f"store may contain {', '.join(STORE_KEYS)}; unknown: {', '.join(unknown)}"
            )

        raw_root = declared.get("root")
        root: Path | None = None
        if raw_root is not None:
            if not isinstance(raw_root, str):
                raise TypeError(f"store.root must be a path string; got {type(raw_root).__name__}")
            candidate = Path(raw_root)
            root = candidate if candidate.is_absolute() else base / candidate

        raw_tables = declared.get("tables", ())
        if isinstance(raw_tables, str) or not isinstance(raw_tables, Sequence):
            raise TypeError("store.tables must be a list of table ids")
        tables = tuple(str(item) for item in raw_tables)
        if len(set(tables)) != len(tables):
            raise ValueError(f"store.tables must not repeat a table id: {', '.join(tables)}")

        return cls(root=root, tables=tables)

    def resolve(self, project_root: Path, workspace_directory: str) -> Path:
        """Where this run's artifacts actually go.

        Defaulting to the workspace directory keeps every existing project working without a spec
        change: `store.root` is a lever, and a lever nobody pulls must leave things where they
        were.
        """
        return self.root if self.root is not None else project_root / workspace_directory

    @property
    def declares_dataset_tables(self) -> bool:
        """Whether this spec DECLARES tables that should become datasets.

        AC-P3 as a consequence of the definition rather than a second rule.

        It has no production caller yet: `cli/run.py` reports the declared tables by reading
        `store.tables` directly, and Step 8 lands the first reader that acts on this. Saying so
        beats claiming a single-reader invariant the module does not currently hold.

        Named for the declaration rather than the act, because the act does not happen yet: nothing
        in the `vqapr run` path turns a declared table into a registered dataset. It was called
        `publishes_datasets`, and a present-tense name for a thing that does not occur is a trap
        for whoever autocompletes it -- the docstring saying otherwise is read only by whoever
        opens the file.
        """
        return bool(self.tables)
