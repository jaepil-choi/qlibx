"""No tracked file may carry a private machine path. This repository is public.

Two test files shipped absolute paths of the form ``/home/<user>/...`` for years
without anyone noticing, because both tests skipped silently whenever the path was
absent — which is everywhere except the machine the path leaked. The existing
store-path guard scans only ``PortfolioDeployConfig`` fields and two named scripts,
so it structurally could not see them (found 2026-07-27 by a workspace-wide probe).

This guard closes the class, not the instances: it walks every *tracked* Python
file and refuses any literal that anchors into a user home directory. Machine-local
inputs belong in environment variables (see ``ECHOLON_LEGACY_BASELINES_ROOT`` and
``ECHOLON_DQS_MIRROR_QMT_CLIENT``), never in the tree.
"""
import re
import subprocess
from pathlib import Path

# Built by concatenation so this file's own source cannot match the pattern it
# scans for (a self-matching probe was a named failure mode of an earlier monitor).
_HOME_PREFIXES = ("/" + "home" + "/", "/" + "Users" + "/")
_PATTERN = re.compile(
    "(?:" + "|".join(re.escape(prefix) for prefix in _HOME_PREFIXES) + r")[A-Za-z0-9_.-]+/"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked_python_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = [_REPO_ROOT / line for line in listed.stdout.splitlines()]
    assert files, "git ls-files returned nothing; the probe is broken, not the tree clean"
    return files


def test_the_probe_can_see_a_positive() -> None:
    """A guard that cannot fail has not passed: prove the pattern flags a real leak."""
    seeded = "baseline = Path('" + "/home/" + "someuser/projects/private_repo/output')"
    assert _PATTERN.search(seeded) is not None


def test_no_tracked_python_file_names_a_user_home_directory() -> None:
    offenders = []
    guard = Path(__file__).resolve()
    for path in _tracked_python_files():
        if path.resolve() == guard:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PATTERN.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "private machine paths in a public repository:\n" + "\n".join(offenders)
    )
