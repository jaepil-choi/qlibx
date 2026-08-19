"""`vqapr new <kind> <id>` — emit a component that already runs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render

_KINDS = {"datamodel": ComponentKind.DATA_MODEL, "strategy": ComponentKind.STRATEGY_MODEL}


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
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return success(
        "component.new",
        kind=str(kind),
        id=args.component_id,
        path=str(target),
        object_name=source.split("class ", 1)[1].split("(", 1)[0],
    )
