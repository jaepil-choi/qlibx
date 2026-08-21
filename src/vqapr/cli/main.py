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
from typing import Any, NoReturn

from vqapr.cli import declare, list_, new, register, run
from vqapr.cli.envelope import UsageError, emit, failure

_COMMANDS: dict[str, Any] = {
    "new": new,
    "register": register,
    "declare": declare,
    "run": run,
    "list": list_,
}


class _Parser(argparse.ArgumentParser):
    """An `ArgumentParser` that refuses through the envelope instead of around it.

    The default `error()` writes prose to stderr and raises `SystemExit`, which is a
    `BaseException` and so passes straight through the handler's `except Exception`. An agent
    calling a command wrong therefore got an empty stdout and a bare exit code, which is the one
    thing `envelope.py` promises cannot happen.

    `--help` and `--version` leave through `exit()` rather than `error()`, so they keep argparse's
    own behaviour untouched.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message, prog=self.prog)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="vqapr")
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
    try:
        args = parser.parse_args(argv)
    except UsageError as error:
        # The command line never reached a handler, so there is no project root to dump beside.
        return emit(failure(error))
    project_root = Path(args.project_root)
    handler: Callable[..., dict[str, Any]] = args.handler
    try:
        payload = handler(args, project_root=project_root)
    except Exception as error:  # every failure leaves through the same envelope
        payload = failure(error, project_root=project_root)
    return emit(payload)
