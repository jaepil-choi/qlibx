"""The properties an agent depends on before it knows anything about vqapr.

Two of them cannot be observed from inside the process:

- **`--help` must survive the console encoding.** `capsys` replaces stdout with a UTF-8 capture,
  so an in-process test passes even when the real console cannot encode the text. Help text
  containing an em dash exited non-zero with empty stdout on a cp949 console and every in-process
  test stayed green, so these run through a real subprocess with the encoding forced.
- **`python -m vqapr` must work**, which is a question about the module, not about `main()`.

The rest assert the refusals an agent hits while learning the surface: a first `list` before
anything exists, a path that was mistyped, a retried command, and a spec that is not finished.
Each of those must arrive as a typed stage rather than as `unhandled`, because `unhandled` tells
an agent the framework broke and sends it to read source instead of fixing its own input.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.cli.main import _COMMANDS, _DESCRIPTIONS, _SUMMARIES, main

_VERBS = tuple(_COMMANDS)


def _run(*argv: str, encoding: str | None = None) -> subprocess.CompletedProcess[bytes]:
    """Invoke the CLI as a real process, optionally through a legacy code page."""
    env = dict(os.environ)
    if encoding is not None:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "vqapr", *argv],
        capture_output=True,
        env=env,
        check=False,
    )


def _envelope(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_every_verb_is_described_in_the_top_level_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A verb list with no descriptions makes an agent guess, which is the whole defect."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0

    printed = capsys.readouterr().out
    for verb in _VERBS:
        assert verb in printed, f"{verb} is missing from --help"
        assert _SUMMARIES[verb] in " ".join(printed.split()), f"{verb} has no summary"


@pytest.mark.parametrize("verb", _VERBS)
def test_each_verb_help_survives_a_legacy_console_encoding(verb: str) -> None:
    """Help must reach the console whatever code page it is using.

    Today's help text is ASCII, so this passes on text alone. It is kept because the text is
    prose and prose acquires an em dash the moment somebody edits it, and the failure mode is
    silent in every in-process test: `capsys` captures UTF-8 and never touches a code page.
    `test_help_is_written_as_bytes_not_through_the_console_codec` is the one that pins the
    mechanism rather than the current text.
    """
    result = _run(verb, "--help", encoding="cp949")

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout, f"{verb} --help produced no output"
    assert not result.stderr, result.stderr.decode("utf-8", "replace")


def test_help_is_written_as_bytes_not_through_the_console_codec() -> None:
    """The parser must not depend on the console being able to encode its help text.

    Stock `argparse` calls `file.write(message)` in `_print_message`, so a description carrying a
    character the code page cannot encode raises `UnicodeEncodeError` *inside* `print_help`:
    exit 1, empty stdout, and a traceback on stderr from the first command an agent runs against
    an unfamiliar verb. `emit()` already writes the envelope as UTF-8 bytes for this exact reason
    and the parser now applies the same discipline.

    Non-ASCII text is injected here rather than asserted in the shipped descriptions, so the
    guarantee holds for whatever the help text later becomes.
    """
    probe = (
        "import sys\n"
        "from vqapr.cli.main import build_parser\n"
        "parser = build_parser()\n"
        "parser.description = 'em dash \\u2014 and hangul \\ud55c\\uae00'\n"
        "parser.parse_args(['--help'])\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="cp949")
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, env=env, check=False
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert "\u2014".encode() in result.stdout, "the em dash did not survive"
    assert "\ud55c\uae00".encode() in result.stdout, "the hangul did not survive"
    assert b"UnicodeEncodeError" not in result.stderr


@pytest.mark.parametrize("verb", _VERBS)
def test_each_verb_help_states_what_the_verb_is(verb: str) -> None:
    """`--help` must answer "what is this", not only "what flags does it take"."""
    result = _run(verb, "--help")
    printed = result.stdout.decode("utf-8")

    assert result.returncode == 0
    # The description's first line is the verb's contract in one sentence.
    assert _DESCRIPTIONS[verb].splitlines()[0] in " ".join(printed.split())


def test_module_entrypoint_matches_the_console_script() -> None:
    """`python -m vqapr` is how a subprocess reaches the CLI without PATH resolution."""
    result = _run("--help")

    assert result.returncode == 0
    assert b"usage: vqapr" in result.stdout


def test_list_succeeds_before_a_workspace_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`list` is the first orienting command. Refusing it starts the session on a failure."""
    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "list", "datasets")

    assert code == 0
    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["items"] == []


def test_a_corrupt_workspace_still_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The empty-directory guard must not become a catch that hides damage.

    A missing workspace is an empty workspace. A workspace that exists and cannot be read is a
    different fact, and reporting it as "zero items" would let an agent build on top of damage.
    """
    workspace = tmp_path / ".vqapr"
    workspace.mkdir()
    (workspace / "workspace.yaml").write_text("{ not: [valid", encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "list", "datasets")

    assert code == 1
    assert payload["ok"] is False


def test_a_missing_input_file_is_typed_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped path is the user's error, and reporting it must not mutate the project.

    This arrived as `stage:"unhandled"` with a traceback dumped into `.vqapr/diagnostics/`, so a
    read-only refusal created a directory as a side effect and told the agent the framework broke.
    """
    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "register", str(tmp_path / "absent.yaml")
    )

    assert code == 1
    assert payload["stage"] == "cli.input"
    assert payload["failures"][0]["code"] == "cli.input.file_missing"
    assert "detail" not in payload
    assert "traceback" not in payload
    assert not (tmp_path / ".vqapr").exists(), "a refusal left a side effect behind"


def test_rerunning_new_refuses_by_name_instead_of_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Retrying is the most common thing an agent does, so the second attempt must be typed."""
    argv = (
        "--project-root",
        str(tmp_path),
        "new",
        "datamodel",
        "alpha",
        "--dataset",
        "prices",
    )
    first_code, _ = _envelope(capsys, *argv)
    assert first_code == 0

    code, payload = _envelope(capsys, *argv)

    assert code == 1
    assert payload["stage"] == "cli.input"
    assert payload["failures"][0]["code"] == "cli.input.file_exists"
    assert "alpha" in payload["failures"][0]["observed"]


def test_an_emitted_run_spec_declares_every_key_run_requires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The template exists so field names are read, not guessed.

    A template missing a key `run` requires would send the agent back to documentation on its
    first run, which is the moment it is least able to recover.
    """
    import yaml

    from vqapr.cli.run import _REQUIRED

    target = tmp_path / "spec.yaml"
    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "new", "run-spec", "--out", str(target)
    )

    assert code == 0
    assert payload["ok"] is True
    assert target.exists()

    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    for key in _REQUIRED:
        assert key in document, f"the emitted template does not declare {key}"


def test_an_emitted_run_spec_explains_each_key(tmp_path: Path) -> None:
    """Values alone are not enough: a placeholder with no comment is still a guess."""
    target = tmp_path / "spec.yaml"
    main(["--project-root", str(tmp_path), "new", "run-spec", "--out", str(target)])

    text = target.read_text(encoding="utf-8")

    assert "vqapr run" in text, "the template does not say what to do with itself"
    assert text.count("#") >= 8, "the template's keys are not explained"


def test_an_incomplete_spec_names_every_missing_key_at_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One reply must carry all of them, and it must stay bounded.

    `examples` is capped at `MAX_EXAMPLES`, so `observed` carries the full list while
    `example_total` reports how many there really were.
    """
    from vqapr.domain.errors import MAX_EXAMPLES

    spec = tmp_path / "thin.yaml"
    spec.write_text("strategy:\n  component: a\n  agenda_id: b\n", encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 1
    assert payload["stage"] == "cli.input"
    detail = payload["failures"][0]
    assert detail["code"] == "cli.input.keys_missing"
    assert detail["example_total"] == 7
    assert len(detail["examples"]) <= MAX_EXAMPLES
    for key in ("valuation", "instruments", "start", "end", "exchange", "execution_input"):
        assert key in detail["observed"], f"{key} was not named"


def test_a_spec_that_is_not_a_mapping_says_what_it_parsed_as(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "bad.yaml"
    spec.write_text("just a bare string\n", encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 1
    assert payload["failures"][0]["code"] == "cli.input.not_a_mapping"
    assert "str" in payload["failures"][0]["observed"]
