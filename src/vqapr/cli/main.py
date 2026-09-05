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

from vqapr.cli import check, list_, new, register, rm, run, show, skill
from vqapr.cli.envelope import UsageError, emit, failure
from vqapr.inputs import VALUE_INVALID, InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME

_COMMANDS: dict[str, Any] = {
    "new": new,
    "register": register,
    "check": check,
    "run": run,
    "list": list_,
    "show": show,
    "rm": rm,
    "skill": skill,
}

_SUMMARIES: dict[str, str] = {
    "new": "scaffold a component, or emit a dataset/execution-input/run declaration template",
    "register": "validate a declaration and add what it declares to the workspace",
    "check": "prove a registered run is ready, reporting every problem at once, without running",
    "run": "freeze a registered run, preflight it, and execute its strategies",
    "list": "show what the workspace holds and what the store recorded",
    "show": "answer questions about one run or one strategy record, from what was frozen",
    "rm": "remove a run's records, or withdraw a registration nothing still names",
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
        "  vqapr new run --out <path>\n"
        "      writes a `runs:` declaration template with every required key commented.\n\n"
        "Nothing is registered by this command. Pass the emitted .yaml to `vqapr register`."
    ),
    "register": (
        "Validate a declaration and add what it declares to the workspace.\n\n"
        "Datasets, sources, execution inputs, components and runs are all "
        "declared in one YAML document. Sections are applied in dependency order, so a valid "
        "document "
        "cannot fail because of the order it was typed in.\n\n"
        "This command mutates the workspace. It refuses with structured evidence rather than "
        "registering something partially."
    ),
    "check": (
        "Prove a registered run is ready, without running it.\n\n"
        "Reports every INDEPENDENT problem at once rather than stopping at the first, so a "
        "declaration can be repaired in one pass instead of one round trip per defect. A check "
        "that could not run because an earlier one failed is reported as blocked, naming what "
        "blocked it, so a partial report never looks complete.\n\n"
        "vqapr writes nothing during a check. Note that judging a component means importing it, "
        "and an imported module is user code that can do as it pleases; the guarantee is about "
        "this package, not a sandbox."
    ),
    "run": (
        "Judge a registered run, freeze it, preflight it, and execute its strategies.\n\n"
        "  vqapr run <run-id> [--strategy <id>]... [--jobs N] [--force]\n"
        "      runs every strategy the run names (or those given), each with its own account "
        "and its own record under .vqapr/runs/<run-id>/strategies/<id>@<fp8>/.\n"
        "  vqapr run <datamodel-run-id>\n"
        "      runs every datamodel the run names, each writing its dataset under "
        ".vqapr/materialized/<dataset-id>/ and its record under "
        ".vqapr/runs/<run-id>/datamodels/<id>@<fp8>/ (record 148: a datamodel is a run)."
        "\n\n"
        "The same judgments `vqapr check` makes are made here before the run is frozen: a run "
        "that would fail `check` is refused rather than executed. Declare a run with "
        "`vqapr new run --out runs.yaml`, register it, and prove it with `vqapr check <run-id>`."
        "\n\n"
        "Every strategy the run names is run, in a single process or under --jobs. A refusal "
        "inside one strategy is that strategy's outcome: the others still run, and the "
        "envelope reports every strategy with a status (ok:false, stage run.strategy_failed, "
        "the failed strategy's refusal in its own block). While a run is executing, "
        "`vqapr list strategies --run <run-id>` shows each strategy's progress."
    ),
    "list": (
        "Show what the workspace already holds.\n\n"
        "Each row carries the identifiers needed as arguments to the next command. "
        "An empty or uninitialised directory reports zero items and succeeds.\n\n"
        "`list runs` lists the registered runs and, beside each, the strategy records the store "
        "holds; `list strategies --run <id>` lists those records, filterable by strategy, "
        "fingerprint, contract and period. Records are found by scanning: no index file means "
        "no shared target for concurrent runs to lose each other's entries on."
    ),
    "show": (
        "Answer questions about one run, or one strategy record.\n\n"
        "  vqapr show run <run-id>            the configuration every strategy shared\n"
        "  vqapr show strategy <run-id>/<strategy-id>@<fp8> [--table <t>] [--limit N]\n"
        "                                     one strategy's output, or its rows\n\n"
        "Reads what the run froze to disk, so it answers from any process. Nothing is "
        "recomputed; re-running to answer a question about a run would be a different run."
    ),
    "rm": (
        "Remove records, or withdraw a registration.\n\n"
        "  vqapr rm run <run-id> [--keep-latest]     a run's records (a live one is refused)\n"
        "  vqapr rm strategy <run-id>/<id>@<fp8>     one strategy's record\n"
        "  vqapr rm run-definition|component <id>\n"
        "                                            a registration nothing live still names"
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
        default=None,
        help=(
            "workspace root: where `.vqapr/` is or will be (default: the current directory; "
            "refused when an ancestor directory already holds a workspace and this one does "
            "not, so a command run from a subdirectory cannot start a second workspace by "
            "accident -- pass the ancestor, or this directory, explicitly)"
        ),
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


def _nearest_workspace_above(start: Path) -> Path | None:
    """The closest ancestor of `start` that holds a workspace document, or `None`."""
    for ancestor in start.parents:
        if (ancestor / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).is_file():
            return ancestor
    return None


def _resolve_project_root(explicit: Path | None) -> Path:
    """The root every command works in, refusing an implicit one that would shadow an ancestor.

    `docs/issues/066`: `vqapr register` run from `work/decl/` created `work/decl/.vqapr` beside
    the project's real workspace and the next `check` refused for datasets registered five
    minutes earlier. Git's discovery rule is the model -- walk up -- but a workspace is written
    to, and silently choosing the parent would put the caller's files in a directory they did
    not name. So an implicit root that has no workspace while an ancestor has one is refused,
    naming both; an explicit `--project-root` is never second-guessed, so a nested workspace is
    still one command away when it is meant.
    """
    if explicit is not None:
        return Path(explicit)
    here = Path.cwd()
    if (here / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).is_file():
        return here
    above = _nearest_workspace_above(here)
    if above is None:
        return here
    raise InputError(
        VALUE_INVALID,
        requirement=(
            "a command run without --project-root must not start a second workspace beneath "
            "an existing one"
        ),
        observed=f"no workspace at {here}; the nearest is at {above}",
        retry=(
            f"run `vqapr --project-root {above} ...` (or cd there), or name this directory "
            f"explicitly with `--project-root {here}` to create a workspace here on purpose"
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as error:
        # The command line never reached a handler, so there is no project root to dump beside.
        return emit(failure(error))
    try:
        project_root = _resolve_project_root(args.project_root)
    except InputError as refused:
        return emit(failure(refused))
    handler: Callable[..., dict[str, Any]] = args.handler
    try:
        payload = handler(args, project_root=project_root)
    except Exception as error:  # every failure leaves through the same envelope
        payload = failure(error, project_root=project_root)
    # Every envelope says WHICH workspace it is about (`docs/issues/066`): a refusal about
    # registration state that names the cure but not the place it looked is correct and not
    # enough to act on. Absolute, so a reader comparing two commands' answers can see when
    # they were about different directories.
    payload["workspace_root"] = str(project_root.resolve())
    return emit(payload)
