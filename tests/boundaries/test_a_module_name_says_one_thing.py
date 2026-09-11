"""A module's file name says one thing: no two modules in the package share a basename.

Owner ruling 2026-09-11 (concept-tree campaign, AC3). Two `store.py`, two `document.py`, two `run.py`,
`report/record.py` beside `record/`, a `Series` in two places -- that is how "the file name and what
it does are too different" read in the tree: a name that means two things makes a reader open both
to learn which one a traceback or a review comment meant.

`base.py` is the one name allowed to repeat, and deliberately: every role's contract module is
called `base.py`, beside the implementations it is the base of (`component/` and each role package
in it), so the repetition says one thing -- "the base of this package".
"""

from __future__ import annotations

import collections
import pathlib

PACKAGE = pathlib.Path(__file__).parents[2] / "src" / "vqapr"

REPEATABLE = frozenset({"__init__.py", "__main__.py", "base.py"})


def test_no_two_modules_share_a_file_name() -> None:
    by_name: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name in REPEATABLE:
            continue
        by_name[path.name].append(path.relative_to(PACKAGE).as_posix())
    repeated = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    assert not repeated, (
        f"these file names mean more than one module: {repeated}. Name each for what it does; "
        "`base.py` is the only name that repeats, because it always means the base of its package."
    )
