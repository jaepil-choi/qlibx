"""`vqapr register <declaration.yaml>` — validate everything declared, then persist it.

**One verb, one file.** A workspace holds two kinds of thing: code the user wrote (a Strategy, a
DataModel, a Constraint, a venue) and facts about the world that code needs (where the data is,
what its columns mean, when decisions happen, at what price they fill). Both are registrations —
both are refused unless they check out, and both live in the same workspace — so both enter here.

`check` is not a separate command. Every path through this file validates before it writes, so a
registration that succeeds is one the framework can use, and nothing lands that cannot be run.

## Why a file and not flags

A component cannot be registered from argv alone without lying about what registration needs. A
DataModel needs the dataset it reads; a Strategy needs its cadence; a dataset needs its
`available_at` column, its logical key, and the field map that gives its columns framework names.
None of that fits a flag, and a command that accepted the component without them would register
something no run could use — the exact "registered but unusable" state this package refuses.

So the declaration is the unit. `vqapr new` emits one beside the component it scaffolds, and
`register` refuses a component that does not bring one.

## What is validated, not merely recorded

- **datasets** — every declared column exists, `available_at` is timezone-aware, and the logical
  key is scanned in full for nulls and duplicates. A dataset whose `(available_at, instrument)`
  repeats is refused with the offending groups as evidence, because a duplicated key silently
  changes what a lookback window contains.
- **execution inputs** — the same schema check over the venue table, plus the fill convention.
- **components** — loaded, constructed, and put through `conformance()`: every contract method
  Flow calls must exist and accept the positional call it makes.
- **configs** — the agenda and component they name must already be registered.

Sections are applied in dependency order, not file order, so a valid document cannot fail because
of how the user happened to type it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.declarations import AUTHORED_KINDS, apply, register_authored
from vqapr.declarations import cli_kind as cli_kind  # re-export: cli/check.py, run.py, list_.py
from vqapr.inputs import read_yaml_mapping

"""The component kinds an author writes as a `.py` and registers directly.

Everything else -- datasets, sources, agendas, configs -- stays in the YAML declaration, because
those ARE declarations: there is no code to point at. A component is different. Its identity is
its source file, and requiring a YAML wrapper to say so made the author write the same fact twice
and kept a Python-authored strategy from being registered by naming it.
"""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "declaration",
        type=Path,
        help=(
            "path to the declaration YAML, or the component kind "
            f"({', '.join(sorted(AUTHORED_KINDS))}) when registering a .py directly"
        ),
    )
    parser.add_argument(
        "component_id",
        nargs="?",
        default=None,
        help="component id, when the first argument is a component kind",
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="path to the .py, when the first argument is a component kind",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    kind = str(args.declaration)
    if kind in AUTHORED_KINDS:
        # The layer returns data; this surface renders it.
        return success("workspace.register", **register_authored(
            kind, getattr(args, "component_id", None), getattr(args, "source", None), project_root
        ))
    declaration = Path(args.declaration)
    document = read_yaml_mapping(declaration, what="a declaration")
    return success(
        "workspace.register",
        registered=apply(
            document, project_root, base=declaration.parent, declaration=declaration
        ),
    )
