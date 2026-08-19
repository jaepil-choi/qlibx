"""`vqapr` entrypoint.

The CLI is a thin layer on purpose. It parses arguments, calls the public facade, and renders one
JSON envelope; it does not explain failures or offer remedies. The package decides deterministically
and the agent skill does the talking (PRD §2.6), so a message invented here would be a second,
unversioned authority.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vqapr.cli import list_, new, register, run
from vqapr.cli.envelope import emit, failure

_COMMANDS: dict[str, Any] = {
    "new": new,
    "register": register,
    "run": run,
    "list": list_,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vqapr")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="workspace root (defaults to the current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, module in _COMMANDS.items():
        subparser = subparsers.add_parser(name)
        module.add_arguments(subparser)
        subparser.set_defaults(handler=module.run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root)
    handler: Callable[..., dict[str, Any]] = args.handler
    try:
        payload = handler(args, project_root=project_root)
    except Exception as error:  # every failure leaves through the same envelope
        payload = failure(error, project_root=project_root)
    return emit(payload)
