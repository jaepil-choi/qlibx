"""Report which plotting libraries this environment has, and how this project installs one.

    python check_plotting_env.py
    python check_plotting_env.py --json

vqapr computes report values and **ships no plotting library and no renderer** (PRD §9.4): a chart
is a renderer the project builds on values it can already read. So the libraries a figure needs are
the project's dependencies, not vqapr's, and on a fresh machine they are usually absent.

**This script installs nothing.** It reports what is missing and prints the command that would
install it, for the user to approve. Adding a dependency changes the project's lockfile and its
reproducibility, which is the user's decision and not a detail to slip past them.

It also never suggests adding anything to vqapr itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path

WANTED = {
    "pandas": "bridges a report's `instants` beside `values` into a frame or series",
    "matplotlib": "the usual renderer for a paper figure; PDF and 300dpi PNG out of the box",
    "numpy": "arrives with pandas; named here so a partial install is visible",
}
"""The pair a paper figure normally needs, and nothing more.

Offering four alternatives per job is how a skill turns a decision into a survey. `pandas` +
`matplotlib` is the default with an escape hatch, not the only possibility -- if the project
already renders with something else, use that instead and do not install these.
"""


def _installed() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for name in WANTED:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def _installer(root: Path, packages: list[str]) -> tuple[str, str]:
    """(how this project manages dependencies, the command that adds exactly *packages*).

    Read from what the project actually has on disk. Guessing `pip install` into a uv-managed
    project writes into an environment the lockfile does not describe, and the next `uv sync`
    silently removes it -- which looks like the install never happened.

    Only what is missing goes into the command. Naming a package the environment already has
    invites a version change nobody asked for, in a lockfile the user then has to review.
    """
    names = " ".join(packages)
    pip = f"{Path(sys.executable).name} -m pip install {names}"
    for parent in (root, *root.parents):
        if (parent / "uv.lock").is_file():
            return "uv", f"uv add --group dev {names}"
        if (parent / "poetry.lock").is_file():
            return "poetry", f"poetry add --group dev {names}"
        if (parent / "Pipfile.lock").is_file():
            return "pipenv", f"pipenv install --dev {names}"
        if (parent / "environment.yml").is_file():
            return "conda", f"conda install {names}"
        if (parent / "pyproject.toml").is_file() or (parent / "requirements.txt").is_file():
            return "pip", pip
    return "", pip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report which plotting libraries are installed and how this project would add "
            "them. Installs nothing."
        )
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="where to look for a lockfile (default: the current directory)",
    )
    args = parser.parse_args(argv)

    found = _installed()
    missing = [name for name, version in found.items() if version is None]
    manager, command = _installer(args.project_root, missing or list(WANTED))

    report = {
        "python": sys.executable,
        "installed": found,
        "missing": missing,
        "dependency_manager": manager,
        "install_command": command,
        "ready": not missing,
    }

    if args.json:
        text = json.dumps(report, indent=2)
    elif not missing:
        have = ", ".join(f"{name} {version}" for name, version in found.items())
        text = f"ready to render: {have}\npython: {sys.executable}"
    else:
        text = "\n".join(
            [
                f"missing: {', '.join(missing)}",
                *(f"  {name} -- {WANTED[name]}" for name in missing),
                "",
                (
                    f"this project uses {manager}. To add them, with the user's agreement:"
                    if manager
                    else "no lockfile or pyproject found above the project root, so how this "
                    "environment is managed is a guess -- ask before running:"
                ),
                f"  {command}",
                "",
                "Do not add them to vqapr. They are the project's renderer, not the package's.",
                "If the project already renders charts with something else, use that instead.",
            ]
        )

    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)
    else:
        stream.write(text.encode("utf-8") + b"\n")
        stream.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
