"""`vqapr new <kind> <id>` — emit a component that runs, and the declaration that registers it.

Two files, because `register` takes a declaration and a component alone cannot be registered. A
scaffold that emitted only the `.py` would leave the user to write that YAML from documentation on
their first command, which is where a first-time user is least able to guess field names.

The emitted declaration is complete and immediately registrable: `vqapr new` then `vqapr register`
is the whole path from nothing to a registered component.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from vqapr.cli.envelope import success
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render

_KINDS = {"datamodel": ComponentKind.DATA_MODEL, "strategy": ComponentKind.STRATEGY_MODEL}

_DECLARATION_KIND = {
    ComponentKind.DATA_MODEL: "datamodel",
    ComponentKind.STRATEGY_MODEL: "strategy",
}


def _declaration(component_id: str, kind: ComponentKind, source: Path, object_name: str) -> str:
    """The registrable declaration for what was just scaffolded.

    Only the component is declared. The dataset it reads, and the agenda it runs on, are facts
    about the user's project rather than about this file, and inventing plausible values for them
    would produce a document that registers something the user did not mean.
    """
    document = {
        "components": {
            component_id: {
                "kind": _DECLARATION_KIND[kind],
                "path": source.name,
                "object_name": object_name,
            }
        }
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=tuple(_KINDS))
    parser.add_argument("component_id")
    parser.add_argument("--dataset", required=True, help="dataset_id the component reads")
    parser.add_argument("--field", default="close")
    parser.add_argument("--lookback", type=int, default=6)
    parser.add_argument("--out", type=Path, default=None)


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    kind = _KINDS[args.kind]
    source = render(
        kind,
        args.component_id,
        dataset_id=args.dataset,
        field=args.field,
        lookback=args.lookback,
    )
    target = args.out or project_root / f"{args.component_id.replace('-', '_')}.py"
    declaration = target.with_suffix(".yaml")
    for path in (target, declaration):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")

    object_name = source.split("class ", 1)[1].split("(", 1)[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    declaration.write_text(
        _declaration(args.component_id, kind, target, object_name), encoding="utf-8"
    )
    return success(
        "component.new",
        kind=str(kind),
        id=args.component_id,
        path=str(target),
        declaration=str(declaration),
        object_name=object_name,
    )
