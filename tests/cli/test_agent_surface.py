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
from datetime import datetime, time
from pathlib import Path

import duckdb
import pytest

from vqapr import public
from vqapr.cli.main import _COMMANDS, _DESCRIPTIONS, _SUMMARIES, main


def _parquet(root: Path, name: str, rows: str) -> Path:
    path = root / name
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path

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


@pytest.mark.parametrize("action", ("install", "remove", "list"))
def test_every_skill_action_accepts_the_same_root_override(action: str) -> None:
    """An option that works on two of three sibling actions reads as a bug, not as a boundary.

    `list` was the one that refused `--into`, and it is the action most likely to be asked about
    somewhere other than the current directory.
    """
    result = _run("skill", action, "--help")

    assert result.returncode == 0
    assert b"--into" in result.stdout, f"skill {action} does not accept --into"


def test_skill_install_is_inspectable_before_it_writes(tmp_path: Path) -> None:
    """An agent must be able to see where a mutating command would write before it runs."""
    (tmp_path / ".git").mkdir()

    result = _run("--project-root", str(tmp_path), "skill", "install", "--dry-run")
    payload = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])

    assert payload["ok"] is True
    assert str(tmp_path) in payload["paths"]["agents"]
    assert not (tmp_path / ".agents").exists(), "a dry run wrote to disk"


def test_installing_then_removing_leaves_nothing_behind(tmp_path: Path) -> None:
    """The install must be reversible, or a testbed cannot be reset between measurements."""
    (tmp_path / ".git").mkdir()

    installed = json.loads(
        _run("--project-root", str(tmp_path), "skill", "install")
        .stdout.decode("utf-8")
        .strip()
        .splitlines()[-1]
    )
    assert installed["ok"] is True
    assert (tmp_path / ".agents/skills/vqapr/SKILL.md").exists()

    _run("--project-root", str(tmp_path), "skill", "remove")

    assert not (tmp_path / ".agents/skills/vqapr/SKILL.md").exists()
    assert not (tmp_path / ".claude/skills/vqapr-skill/SKILL.md").exists()


def test_the_maintainer_readme_is_not_installed_as_agent_guidance(tmp_path: Path) -> None:
    """`agent/skill/README.md` addresses whoever maintains that directory.

    Shipping it into the install would give an agent a second document to treat as authority, and
    that document talks about what the directory should contain rather than about using vqapr.
    """
    (tmp_path / ".git").mkdir()

    _run("--project-root", str(tmp_path), "skill", "install")

    installed = {path.name for path in (tmp_path / ".agents/skills/vqapr").iterdir()}
    assert "SKILL.md" in installed
    assert "README.md" not in installed


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


_RUN_KEYS = (
    "strategies",
    "valuation",
    "instruments",
    "start",
    "end",
    "exchange",
    "execution_input",
    "initial_account",
)
"""Every key a `runs:` entry declares before `vqapr run` can execute it.

`RunDefinition` tolerates an absent period, venue, execution input and account because other
callers supply them another way; `run` continues into `preflight_run`, which refuses without them.
Pinned as a literal rather than imported: the template is judged against what the reader needs to
type, and a constant that moved with the code would make this test pass for any template.
"""


def test_an_emitted_run_declares_every_key_run_requires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The template exists so field names are read, not guessed.

    A template missing a key `run` requires would send the agent back to documentation on its
    first run, which is the moment it is least able to recover. The keys live under the run's
    own id inside `runs:`, since a run is a registered declaration (record 139).
    """
    import yaml

    target = tmp_path / "runs.yaml"
    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "new", "run", "--out", str(target)
    )

    assert code == 0
    assert payload["ok"] is True
    assert target.exists()

    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert list(document) == ["runs"], "the template is one `runs:` section and nothing else"
    (run,) = document["runs"].values()
    for key in _RUN_KEYS:
        assert key in run, f"the emitted template does not declare {key}"
    assert run["strategies"], "a run names at least one strategy"


def test_an_emitted_run_explains_each_key(tmp_path: Path) -> None:
    """Values alone are not enough: a placeholder with no comment is still a guess."""
    target = tmp_path / "runs.yaml"
    main(["--project-root", str(tmp_path), "new", "run", "--out", str(target)])

    text = target.read_text(encoding="utf-8")

    assert "vqapr run" in text, "the template does not say what to do with itself"
    assert "vqapr register" in text, "the template does not say it must be registered first"
    assert text.count("#") >= 8, "the template's keys are not explained"


def test_a_retired_run_spec_handed_to_run_is_refused_naming_the_runs_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One reply must say where the shape went, not parse the file as if it had not moved.

    A `strategy:` file is the run spec of before record 139. `run` takes a registered run id, or
    a materialization spec; the old file is refused by name with the three commands that replace
    it, so a reader following stale notes gets the new path in one round trip.
    """
    spec = tmp_path / "thin.yaml"
    spec.write_text("strategy:\n  component: a\n  agenda_id: b\n", encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 1
    assert payload["stage"] == "cli.input"
    detail = payload["failures"][0]
    assert detail["code"] == "cli.input.value_invalid"
    assert "runs:" in detail["requirement"]
    assert "strategy:" in detail["observed"]
    for command in ("vqapr new run", "vqapr register", "vqapr run <run-id>"):
        assert command in detail["fix"], f"the fix does not name {command}"
    assert detail["source"]["key_path"] == "strategy"


def test_a_dataset_template_covers_every_required_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-003: there was no dataset scaffold, and register --help named no required keys.

    The template must declare every key that `register` requires so that a first-time reader
    discovers the schema by reading a file, not by collecting one ValueError per retry.
    """
    import yaml

    target = tmp_path / "ds.yaml"
    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "new", "dataset", "--out", str(target)
    )

    assert code == 0 and payload["ok"] is True
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    dataset = next(iter(document["datasets"].values()))
    for key in ("source_id", "path", "instrument_field", "available_at", "key_fields", "fields"):
        assert key in dataset, f"template does not declare {key}"


def test_a_dataset_template_explains_available_at(tmp_path: Path) -> None:
    """The critical field must not be a bare placeholder.

    Getting `available_at` wrong is a look-ahead the framework cannot detect, so the template
    must explain what it means rather than hoping the reader already knows.
    """
    main(["--project-root", str(tmp_path), "new", "dataset", "--out", str(tmp_path / "ds.yaml")])

    text = (tmp_path / "ds.yaml").read_text(encoding="utf-8")
    assert "available" in text.lower()
    assert "look-ahead" in text.lower() or "when" in text.lower()
    assert "round-trip" in text
    assert "assume_timezone" in text


def test_the_installed_skill_requires_proof_of_timezone_localization(tmp_path: Path) -> None:
    """A timezone-aware schema can still carry a confidently wrong instant.

    A pyarrow cast from naive to timezone-aware preserves the epoch value rather than interpreting
    the wall clock in that zone. Registration cannot diagnose the meaning of a valid timestamp,
    so the skill must make one known-instant round-trip part of preparation, not an optional
    debugging trick learned after a failed run.
    """
    (tmp_path / ".git").mkdir()
    main(["--project-root", str(tmp_path), "skill", "install"])

    text = (tmp_path / ".agents/skills/vqapr/SKILL.md").read_text(encoding="utf-8")

    assert "known instant" in text
    assert "round-trip" in text
    assert "assume_timezone" in text
    assert "does **not** mean" in text


def test_the_installed_skill_points_at_the_public_library_surface(tmp_path: Path) -> None:
    """The distribution ships ~160 helpers and the skill never said so.

    A first-time journey set out to hand-roll Fama-French 30/70 breakpoints and a bucket
    assignment, both of which the package already exports, and found them only by running
    `dir(vqapr.public)` out of habit. Four of that journey's findings were answerable from this one
    module. The CLI help is authoritative for verbs, but it lists no library surface at all, so
    nothing pointed an agent here.

    Asserted on the INSTALLED skill rather than the source, because that is the text an agent
    actually reads.
    """
    (tmp_path / ".git").mkdir()
    main(["--project-root", str(tmp_path), "skill", "install"])

    text = (tmp_path / ".agents/skills/vqapr/SKILL.md").read_text(encoding="utf-8")

    assert "vqapr.public" in text, "the skill still never names the library surface"
    assert "dir(public)" in text or "dir(vqapr.public)" in text, (
        "the skill must show how to enumerate the surface, since the CLI help does not list it"
    )

    # The three families, each by a name that is really exported.
    for symbol in (
        "fama_french_cut_points",
        "fama_french_assign",
        "neutralize",
        "information_coefficient",
    ):
        assert symbol in text, f"the skill does not name {symbol}"
        assert hasattr(public, symbol), f"the skill names {symbol}, which is not exported"


def test_missing_declaration_keys_arrive_as_typed_failures_not_unhandled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-005: a missing required key produced stage:unhandled with empty failures[].

    The installed SKILL.md instructs agents to read `failures` first, so an empty failures array
    on the most common mistake actively misleads.
    """
    spec = tmp_path / "ds.yaml"
    spec.write_text(
        "datasets:\n  prices:\n    instrument_field: ticker\n", encoding="utf-8"
    )

    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "register", str(spec)
    )

    assert code == 1
    assert payload["stage"] != "unhandled", "should be a typed refusal, not unhandled"
    assert payload["failures"], "failures must not be empty"
    missing_codes = [f["code"] for f in payload["failures"]]
    assert all("key_missing" in c for c in missing_codes)
    # All missing keys in one refusal, not one per round trip.
    assert len(payload["failures"]) >= 3, (
        f"expected all missing keys at once, got {len(payload['failures'])}"
    )


def test_unknown_section_sources_explains_inline_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-007: register demanded source_id then rejected the sources: section it implied.

    The refusal must explain where a source actually goes.
    """
    spec = tmp_path / "ds.yaml"
    spec.write_text(
        "datasets:\n  p: {source_id: s, path: x, instrument_field: i,"
        " available_at: t, key_fields: [t,i], fields: {c: c}}\n"
        "sources:\n  s: {path: x}\n",
        encoding="utf-8",
    )

    code, payload = _envelope(
        capsys, "--project-root", str(tmp_path), "register", str(spec)
    )

    assert code == 1
    assert payload["stage"] == "declaration.read"
    observed = payload["failures"][0]["observed"]
    assert "inline" in observed.lower() or "pair" in observed.lower()


def test_a_rejected_enum_value_names_every_permitted_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bad enum value must not arrive as an unhandled KeyError.

    `fill.selector` was a raw `FillSelector[value.upper()]` lookup, so a wrong value crashed with
    a traceback instead of a refusal. Measured: a reader spent six consecutive attempts on
    price vocabulary (close, market, vwap, next_open) because the field name reads as "which
    price" while the members are scheduling words. Guessing cannot converge on a vocabulary the
    field name argues against, so the refusal has to carry the list.
    """
    spec = tmp_path / "ei.yaml"
    spec.write_text(
        "execution_inputs:\n  krx:\n    table:\n      source_id: s\n      path: x.parquet\n"
        "      trade_at_field: t\n      instrument_field: i\n      is_tradable_field: ok\n"
        "      price_fields: {close: close}\n    fill:\n      selector: next_open\n"
        '      at: "15:30"\n      timezone: Asia/Seoul\n      trade_price: close\n',
        encoding="utf-8",
    )

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "register", str(spec))

    assert code == 1
    assert payload["stage"] != "unhandled"
    assert payload["failures"], "a bad enum value produced no structured failure"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.read.value_not_permitted"
    for member in ("same_day", "next_eligible"):
        assert member in failure["requirement"], f"{member} was not named"
    assert failure["examples"], "permitted values must ride as examples"


def test_an_execution_input_template_covers_every_required_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No scaffold existed for this kind, and it is the deepest nesting `register` accepts.

    Measured: ten required keys across two nested blocks, discovered one refusal at a time.
    """
    import yaml

    target = tmp_path / "ei.yaml"
    code, _ = _envelope(
        capsys, "--project-root", str(tmp_path), "new", "execution-input", "--out", str(target)
    )

    assert code == 0
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    declared = next(iter(document["execution_inputs"].values()))
    for key in (
        "source_id",
        "path",
        "trade_at_field",
        "instrument_field",
        "is_tradable_field",
        "price_fields",
    ):
        assert key in declared["table"], f"table does not declare {key}"
    for key in ("selector", "at", "timezone", "trade_price"):
        assert key in declared["fill"], f"fill does not declare {key}"


def test_an_execution_input_template_emits_a_valid_selector(tmp_path: Path) -> None:
    """The emitted value must be one the validator accepts, not a placeholder to guess at."""
    import yaml

    from vqapr.exchange.conventions import FillSelector

    target = tmp_path / "ei.yaml"
    main(["--project-root", str(tmp_path), "new", "execution-input", "--out", str(target)])

    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    declared = next(iter(document["execution_inputs"].values()))
    assert declared["fill"]["selector"].upper() in FillSelector.__members__


def test_every_section_a_run_needs_has_a_template(tmp_path: Path) -> None:
    """`vqapr new`'s choice list is the de-facto index of what a declaration may contain.

    A reader who scaffolds every kind offered, fills them in, and runs must not then meet a
    section no template ever named. That is what happened: `strategy_configs` was reachable only
    by knowing in advance that it existed, and the run failed at
    `workspace.strategy_config.register.missing` after every visible step had succeeded.

    This test fails if `register` learns a section a run needs and `new` is not taught to emit it.
    """
    from vqapr.cli.new import _AGENDAS_TEMPLATE, _DATASET_TEMPLATE, _EXECUTION_INPUT_TEMPLATE

    emitted = "\n".join((_DATASET_TEMPLATE, _EXECUTION_INPUT_TEMPLATE, _AGENDAS_TEMPLATE))

    for section in (
        "datasets",
        "execution_inputs",
        "agendas",
        "strategy_configs",
        "valuation_configs",
    ):
        assert f"{section}:" in emitted, f"no template emits a {section} section"


def test_an_agendas_template_registers_after_its_placeholders_are_filled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The template must be a working document, not a shape to be corrected.

    Registered against a real dataset so the `from_dataset` path is exercised: an agenda that
    follows a dataset's own days is the common case and the one the template leads with.
    """
    import yaml

    prices = _parquet(
        tmp_path,
        "prices.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 06:30:00+09', 'A', 100.0),
             (TIMESTAMPTZ '2024-03-06 06:30:00+09', 'A', 101.0)
           ) AS t(available_at, instrument, close)""",
    )
    dataset = tmp_path / "d.yaml"
    dataset.write_text(
        "datasets:\n  krx:\n"
        "    source_id: krx-source\n"
        f"    path: {prices.as_posix()}\n"
        "    instrument_field: instrument\n"
        "    available_at: available_at\n"
        "    grain: instrument_instant\n"
        "    key_fields: [available_at, instrument]\n"
        "    fields: {close: close}\n",
        encoding="utf-8",
    )
    assert _envelope(capsys, "--project-root", str(tmp_path), "register", str(dataset))[0] == 0

    target = tmp_path / "agendas.yaml"
    code, _ = _envelope(
        capsys, "--project-root", str(tmp_path), "new", "agendas", "--out", str(target)
    )
    assert code == 0

    # The two placeholders the template tells the reader to replace. `strategy_configs` names a
    # component that does not exist in this test, so it is dropped rather than filled -- the
    # agendas and the valuation binding are what this asserts.
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    document.pop("strategy_configs")
    for agenda in document["agendas"].values():
        agenda["from_dataset"] = "krx"
    target.write_text(yaml.safe_dump(document), encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "register", str(target))

    assert code == 0, payload
    assert sorted(payload["registered"]["agendas"]) == ["daily-rebalance", "daily-valuation"]
    assert payload["registered"]["valuation_configs"] == ["daily-valuation"]


def test_the_run_template_says_naming_an_agenda_is_not_binding_it(tmp_path: Path) -> None:
    """The template's own header claimed completeness it did not have.

    It read "every required key is shown" while omitting that the components it names must also
    be bound by a registered config. Every key of the run spec *was* present -- the sentence was
    true about this file and false about what running it needs, which is the harder kind of wrong
    to catch, because nothing about the emitted file looks incomplete.

    A run declaration names its strategies by id and no longer restates the agenda at all: the
    binding is the registered `strategy_configs` entry, and the template says so.
    """
    target = tmp_path / "runs.yaml"
    main(["--project-root", str(tmp_path), "new", "run", "--out", str(target)])

    text = target.read_text(encoding="utf-8")

    assert "vqapr new agendas" in text, "the template does not say where the binding comes from"
    assert "nothing here registers or binds them" in text
    assert "strategy_configs" in text, "the template does not name the binding's own section"


def test_generated_schedule_and_execution_defaults_are_causally_compatible(
    tmp_path: Path,
) -> None:
    """Independent templates must not put a decision and its fill at the same instant."""
    import yaml

    agendas = tmp_path / "agendas.yaml"
    execution = tmp_path / "execution.yaml"
    main(["--project-root", str(tmp_path), "new", "agendas", "--out", str(agendas)])
    main(["--project-root", str(tmp_path), "new", "execution-input", "--out", str(execution)])

    agenda_document = yaml.safe_load(agendas.read_text(encoding="utf-8"))
    execution_document = yaml.safe_load(execution.read_text(encoding="utf-8"))
    strategy_at = time.fromisoformat(agenda_document["agendas"]["daily-rebalance"]["at"])
    fill = next(iter(execution_document["execution_inputs"].values()))["fill"]
    fill_at = time.fromisoformat(fill["at"])

    assert strategy_at < fill_at
    assert "STRICTLY LATER" in execution.read_text(encoding="utf-8")


def test_generated_run_boundaries_name_actual_instants(tmp_path: Path) -> None:
    """A bare date is not an instant and was rejected by the runner the template fed it to."""
    import yaml

    target = tmp_path / "runs.yaml"
    main(["--project-root", str(tmp_path), "new", "run", "--out", str(target)])
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    (run,) = document["runs"].values()

    for key in ("start", "end"):
        boundary = datetime.fromisoformat(run[key])
        assert boundary.utcoffset() is not None, f"{key} is not timezone-aware"


def test_the_skill_names_launcher_and_immutable_setup_recovery(tmp_path: Path) -> None:
    """The first command and first correction must not require source or prior uv knowledge."""
    (tmp_path / ".git").mkdir()
    main(["--project-root", str(tmp_path), "skill", "install"])
    text = (tmp_path / ".agents/skills/vqapr/SKILL.md").read_text(encoding="utf-8")

    assert "uv run vqapr --help" in text
    # Updated, not deleted, by `fix/023-narrow-the-provenance-promise`. The sentence still exists
    # and still says one id means one declaration -- what changed is that it no longer claims
    # re-registering CHANGED CONTENT under the same id is refused, which `docs/issues/009`
    # deliberately made false and `tests/flow/test_edit_loop.py` proves is false.
    assert "Registrations are immutable identities" in text
    assert "register a *different* declaration" not in text
    assert "--force` to replace it in place" in text
    assert "project-local" in text and "`.vqapr/`" in text
    assert "obtain approval for the destructive reset" in text


def test_a_scaffolded_component_is_always_a_loadable_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`register` imports the component, so an extensionless --out fails one command later.

    Reporting success and then refusing the file at the next command puts the failure where the
    flag that caused it is no longer visible.
    """
    code, payload = _envelope(
        capsys,
        "--project-root",
        str(tmp_path),
        "new",
        "datamodel",
        "alpha",
        "--dataset",
        "prices",
        "--out",
        str(tmp_path / "comp"),
    )

    assert code == 0
    assert payload["path"].endswith(".py"), payload["path"]
    assert (tmp_path / "comp.py").exists()
    assert (tmp_path / "comp.yaml").exists()


def test_project_root_after_subcommand_explains_position(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F-004: --project-root after the subcommand was rejected with no explanation."""
    code, payload = _envelope(capsys, "list", "datasets", "--project-root", "/tmp")

    assert code == 1
    assert "before the subcommand" in payload["error"]


def test_a_spec_that_is_not_a_mapping_says_what_it_parsed_as(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "bad.yaml"
    spec.write_text("just a bare string\n", encoding="utf-8")

    code, payload = _envelope(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 1
    assert payload["failures"][0]["code"] == "cli.input.not_a_mapping"
    assert "str" in payload["failures"][0]["observed"]
