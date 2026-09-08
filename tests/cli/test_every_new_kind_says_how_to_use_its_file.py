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
caller's actual question -- *what do I do with this file?* -- with `declaration`. Record 148
retired `agendas` (a run declares its own sessions and wall time), so eight kinds remained;
record 172 added `sample`, which writes a directory rather than a file and reports the
declaration inside it.
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
    # The filled-in form beside the blank ones (record 172): a whole journey, one declaration.
    ("sample", ()),
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
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((result.stdout or result.stderr).strip().splitlines()[-1])


def test_every_kind_is_covered_by_this_test() -> None:
    """A new kind must be declared here rather than silently skipping coverage."""
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

    This is the loop they planned to write. It used to raise `KeyError` on four of the nine kinds
    of the time, and then had to branch on `registrable` for the run spec. Every kind is
    registrable now.
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
        encoding="utf-8",
        timeout=120,
    )

    assert result.returncode != 0, "the placeholder ids registered; the template names real ids?"
    refusal = json.loads((result.stdout or result.stderr).strip().splitlines()[-1])
    assert refusal["stage"] != "unhandled"
    codes = [failure["code"] for failure in refusal["failures"]]
    assert codes == ["run.reference_invalid"], codes
    assert "declaration.unknown_section" not in codes, "`runs:` is a known section now"


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


def test_new_datamodel_emits_the_run_that_computes_it(tmp_path: Path) -> None:
    """The declaration says how to RUN the file, not only how to register it (record 148).

    A datamodel is a `runs:` entry with `datamodels:` since the spec file retired, and the one
    thing a scaffold knows that a reader would otherwise type by hand is that entry: the run's
    sessions are the dataset the model reads, its output is named after the model, and the
    universe and period are placeholders to fill. A strategy's run needs a venue, an execution
    input and an account, which are facts about the project rather than about the file, so a
    strategy scaffold still declares the component alone.
    """
    import yaml

    body = _new(tmp_path, "datamodel", ("dm", "--dataset", "prices"))
    document = yaml.safe_load(Path(body["declaration"]).read_text(encoding="utf-8"))

    assert set(document) == {"components", "runs"}
    assert list(document["components"]) == ["dm"]
    assert list(document["runs"]) == ["dm-run"]
    run = document["runs"]["dm-run"]
    assert run["sessions_from"] == "prices", "the run's sessions are the dataset the model reads"
    assert run["timezone"] == "Asia/Seoul" and run["at"] == "16:00"
    assert run["datamodels"] == {"dm": {"dataset_id": "dm-values", "value_fields": ["value"]}}
    assert "strategies" not in run
    assert run["instruments"] == ["INSTRUMENT_A", "INSTRUMENT_B"], "placeholders, not guesses"
    for key in ("start", "end"):
        assert key in run

    strategy = _new(tmp_path, "strategy", ("st", "--dataset", "prices"))
    assert "runs" not in yaml.safe_load(Path(strategy["declaration"]).read_text(encoding="utf-8"))
