"""`vqapr` entrypoint.

The CLI is a thin layer on purpose. It parses arguments, calls the public facade, and renders one
JSON envelope.

**Usage is the CLI's to state; remedy is the skill's.** The two are different authorities and the
split is what keeps them from competing. `--help` must answer "what is this command and what does
it take" without the reader opening a document, because a reader who has to guess a verb's meaning
has already lost the time the envelope was designed to save. What the CLI still does not do is
explain *how to recover*: the package decides deterministically and the agent skill does the
talking (PRD §2.6), so a remedy invented here would be a second, unversioned authority.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn

from vqapr.cli import list_, new, register, run, skill
from vqapr.cli.envelope import UsageError, emit, failure

_COMMANDS: dict[str, Any] = {
    "new": new,
    "register": register,
    "run": run,
    "list": list_,
    "skill": skill,
}

_SUMMARIES: dict[str, str] = {
    "new": "scaffold a component, or emit a dataset/run-spec declaration template",
    "register": "validate a declaration and add what it declares to the workspace",
    "run": "freeze a run spec, preflight it, and execute the simulation",
    "list": "show what the workspace already holds",
    "skill": "install the agent skill into this project, or remove and inspect it",
}
"""One line per verb, shown in `vqapr --help`.

These exist because the verb set alone is not self-explanatory: `new`, `register`, `run`, `list`
read as generic English and an agent that has to guess which one materializes data will guess
wrong. The summary is the cheapest possible answer to "what is this", and it costs one line.
"""

_DESCRIPTIONS: dict[str, str] = {
    "new": (
        "Emit a starting point.\n\n"
        "  vqapr new datamodel|strategy <id> --dataset <d>\n"
        "      writes a component .py that runs as written, plus the .yaml that registers it.\n"
        "  vqapr new dataset --out <path>\n"
        "      writes a dataset declaration template with every required key commented.\n"
        "  vqapr new execution-input --out <path>\n"
        "      writes the venue-table declaration a run fills against.\n"
        "  vqapr new run-spec --out <path>\n"
        "      writes a run spec template with every required key, each one commented.\n\n"
        "Nothing is registered by this command. Pass the emitted .yaml to `vqapr register`."
    ),
    "register": (
        "Validate a declaration and add what it declares to the workspace.\n\n"
        "Datasets, sources, execution inputs, components, agendas and configs are all declared "
        "in one YAML document. Sections are applied in dependency order, so a valid document "
        "cannot fail because of the order it was typed in.\n\n"
        "This command mutates the workspace. It refuses with structured evidence rather than "
        "registering something partially."
    ),
    "run": (
        "Freeze a run spec, preflight it, and execute the simulation.\n\n"
        "The spec names already-registered components by id; it does not redeclare them. "
        "Preflight refuses any drift between the spec and what is registered.\n\n"
        "Write a starting spec with `vqapr new run-spec --out spec.yaml`."
    ),
    "list": (
        "Show what the workspace already holds.\n\n"
        "Each row carries the identifiers needed as arguments to the next command. "
        "An empty or uninitialised directory reports zero items and succeeds."
    ),
    "skill": (
        "Install the agent skill into this project, or remove and inspect it.\n\n"
        "Installs to .agents/skills/vqapr/, and with --target claude|both also writes a thin "
        "adapter under .claude/skills/ that points at it. The project root is the nearest .git "
        "ancestor unless --into overrides it. AGENTS.md and CLAUDE.md are never touched."
    ),
}
"""What each verb is, written for the agent reading `--help`.

Deliberately not the module docstrings. Those are written for whoever maintains the file and
argue about mechanism and history; an agent asking "what is this verb" needs the contract and
the next command, not the rationale.
"""


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
        if "--project-root" in message and "unrecognized" in message:
            message = (
                "--project-root must come before the subcommand: "
                "vqapr --project-root <dir> <command>. "
                "The current directory is the default when omitted."
            )
        raise UsageError(message, prog=self.prog)

    def _print_message(self, message: str, file: Any = None) -> None:
        """Write help as UTF-8 bytes rather than through the inherited console encoding.

        `emit()` already does this for the envelope and the reason applies verbatim here: a legacy
        code page (cp949 on a Korean Windows console) cannot encode an em dash, so argparse's own
        `file.write` raised `UnicodeEncodeError` and `--help` exited non-zero with empty stdout.

        `--help` is the first thing an agent runs against an unfamiliar verb. Losing it to the
        console encoding defeats the one guarantee this surface exists to make.
        """
        if not message:
            return
        stream = file or sys.stdout
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            stream.write(message)
            return
        buffer.write(message.encode("utf-8"))
        buffer.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="vqapr")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="workspace root (defaults to the current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, module in _COMMANDS.items():
        summary = _SUMMARIES[name]
        subparser = subparsers.add_parser(
            name,
            help=summary,
            description=_DESCRIPTIONS[name],
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
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
