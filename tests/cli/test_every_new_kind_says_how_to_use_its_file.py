"""Every `vqapr new` kind says what to do with the file it wrote.

`docs/issues/026`. `new --help` promised:

    Every kind reports the file to hand `vqapr register` as `declaration`

and four of the nine kinds -- `dataset`, `run-spec`, `agendas`, `execution-input` -- reported `path`
only. The reporter had read that as a guarantee across all nine and planned to script off it.

The promise was wrong in **both** directions then. Four kinds did not emit the key, and one of
those four could not honestly emit it: a run SPEC was not registrable, so the envelope answered
`registrable: false` for it and the help said so.

Since record 139 a run is a `runs:` section of a declaration document, so the one exception is
gone: `vqapr new run` emits a declaration `vqapr register` takes, and every kind answers the
caller's actual question -- *what do I do with this file?* -- with `declaration`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("datamodel", ("dm", "--dataset", "prices")),
    ("strategy", ("st", "--dataset", "prices")),
    ("constraint", ("c",)),
    ("exchange", ("ex",)),
    ("instruments", ()),
    ("dataset", ()),
    ("run", ()),
    ("agendas", ()),
    ("execution-input", ()),
)


def _new(root: Path, kind: str, extra: tuple[str, ...]) -> dict:
    target = root / f"{kind}.out"
    result = subprocess.run(
        [
            sys.executable, "-m", "vqapr", "--project-root", str(root),
            "new", kind, *extra, "--out", str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((result.stdout or result.stderr).strip().splitlines()[-1])


def test_all_nine_kinds_are_covered_by_this_test() -> None:
    """A tenth kind must be declared here rather than silently skipping coverage."""
    import argparse

    from vqapr.cli.new import add_arguments

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    kind_action = next(a for a in parser._actions if a.dest == "kind")

    assert set(kind_action.choices) == {kind for kind, _ in _KINDS}


@pytest.mark.parametrize(("kind", "extra"), _KINDS, ids=[k for k, _ in _KINDS])
def test_the_envelope_says_what_to_do_with_the_file(
    tmp_path: Path, kind: str, extra: tuple[str, ...]
) -> None:
    """Either it names the declaration to register, or it says it is not registrable."""
    body = _new(tmp_path, kind, extra)

    if body.get("registrable", True):
        assert "declaration" in body, (
            f"{kind} reports no `declaration` and does not say it is unregistrable, so a caller "
            "reading one key across kinds gets a KeyError here"
        )
        assert Path(body["declaration"]).is_file()
    else:
        assert "declaration" not in body, (
            f"{kind} says it is not registrable but still names a declaration to register"
        )


def test_a_script_can_read_one_field_across_every_kind(tmp_path: Path) -> None:
    """The reporter's actual use case, run end to end.

    This is the loop they planned to write. It used to raise `KeyError` on four of the nine, and
    then had to branch on `registrable` for the run spec. Every kind is registrable now.
    """
    registrable: list[str] = []
    for kind, extra in _KINDS:
        body = _new(tmp_path, kind, extra)
        if body.get("registrable", True):
            registrable.append(body["declaration"])  # the read that used to raise

    assert len(registrable) == len(_KINDS), "every kind is registrable"


def test_the_emitted_run_template_is_refused_for_its_placeholders_not_for_its_shape(
    tmp_path: Path,
) -> None:
    """The premise behind `declaration` on the run kind, checked rather than asserted.

    A run declaration IS registrable, so the emitted file must be one `register` reads all the
    way through. What stops it is the placeholders -- `my-alpha`, `my-venue`, `my-exec` name
    nothing in an empty workspace -- and that is a typed reference refusal, not a shape refusal
    and not an unknown section. If `register` ever stopped understanding `runs:`, this fails.
    """
    body = _new(tmp_path, "run", ())
    assert body.get("registrable", True) is True
    assert body["declaration"] == body["path"]

    result = subprocess.run(
        [
            sys.executable, "-m", "vqapr", "--project-root", str(tmp_path),
            "register", body["declaration"],
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, "the placeholder ids registered; the template names real ids?"
    refusal = json.loads((result.stdout or result.stderr).strip().splitlines()[-1])
    assert refusal["stage"] != "unhandled"
    codes = [failure["code"] for failure in refusal["failures"]]
    assert codes == ["workspace.run.register.reference"], codes
    assert "declaration.read.unknown_section" not in codes, "`runs:` is a known section now"


def test_the_help_promises_the_key_for_every_kind_again() -> None:
    """The help was the source of the expectation, so it has to say what is now true.

    It stopped overpromising when the run spec was the exception; with the exception gone it
    promises the key for every kind and says what the run declaration is for.
    """
    import argparse

    from vqapr.cli.new import add_arguments

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    kind_help = next(a for a in parser._actions if a.dest == "kind").help or ""

    assert "Every kind reports the file to hand `vqapr register` as `declaration`" in kind_help
    assert "registrable: false" not in kind_help, "no kind answers that any more"
    assert "`runs:`" in kind_help and "vqapr run <run-id>" in kind_help
