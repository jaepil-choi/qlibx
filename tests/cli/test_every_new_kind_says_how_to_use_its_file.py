"""Every `vqapr new` kind says what to do with the file it wrote.

`docs/issues/026`. `new --help` promised:

    Every kind reports the file to hand `vqapr register` as `declaration`

and four of the nine kinds -- `dataset`, `run-spec`, `agendas`, `execution-input` -- reported `path`
only. The reporter had read that as a guarantee across all nine and planned to script off it.

The promise was wrong in **both** directions. Four kinds did not emit the key, and one of those
four *cannot honestly emit it*: a run spec is not registrable. `vqapr register` refuses it with
`declaration.read.unknown_section`, because a spec names components rather than declaring any.
`vqapr run` is what takes it.

So the envelope now answers the question the caller actually has -- *what do I do with this
file?* -- with `declaration` where the answer is `register`, and `registrable: false` where it is
not.
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
    ("run-spec", ()),
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

    This is the loop they planned to write. It used to raise `KeyError` on four of the nine.
    """
    registrable: list[str] = []
    for kind, extra in _KINDS:
        body = _new(tmp_path, kind, extra)
        if body.get("registrable", True):
            registrable.append(body["declaration"])  # the read that used to raise

    assert len(registrable) == len(_KINDS) - 1, "exactly one kind is not registrable"


def test_a_run_spec_really_is_not_registrable(tmp_path: Path) -> None:
    """The premise behind the one exception, checked rather than asserted.

    If `register` ever learns to take a run spec, `registrable: false` becomes a lie and this
    fails.
    """
    body = _new(tmp_path, "run-spec", ())
    assert body["registrable"] is False

    result = subprocess.run(
        [
            sys.executable, "-m", "vqapr", "--project-root", str(tmp_path),
            "register", body["path"],
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, "a run spec registered successfully; registrable: false is wrong"


def test_the_help_no_longer_promises_the_key_for_every_kind() -> None:
    """The help was the source of the expectation, so it has to stop overpromising."""
    import argparse

    from vqapr.cli.new import add_arguments

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    kind_help = next(a for a in parser._actions if a.dest == "kind").help or ""

    assert "Every registrable kind" in kind_help
    assert "registrable: false" in kind_help
