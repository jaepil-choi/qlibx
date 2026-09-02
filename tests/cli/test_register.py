"""`register` is the one door into a workspace, so its refusals are pinned here.

`test_commands.py` drives the happy path end to end: `register` the data, `new` a strategy,
`register` the declaration `new` emitted, then `run`. What is pinned here is the part a happy path
cannot show — that a declaration which would produce an unusable workspace is refused before
anything is written, and that the validation is real rather than transcription.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _parquet(root: Path, name: str, rows: str) -> Path:
    path = root / name
    con = duckdb.connect()
    try:
        con.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _prices(root: Path) -> Path:
    return _parquet(
        root,
        "prices.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
             (TIMESTAMPTZ '2024-03-06 03:00:00+09', 'A', 101.0)
           ) AS t(available_at, instrument, close)""",
    )


def _dataset_document(observation: Path, **overrides: str) -> str:
    fields = {
        "source_id": "price-source",
        "path": observation.as_posix(),
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": "[available_at, instrument]",
        "fields": "{close: close}",
    }
    fields.update(overrides)
    body = "\n".join(f"    {key}: {value}" for key, value in fields.items())
    return f"datasets:\n  prices:\n{body}\n"


def _write(root: Path, name: str, body: str) -> str:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_duplicated_logical_key_is_refused_with_the_offending_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The validation that matters most, because nothing downstream can detect it.

    A repeated `(available_at, instrument)` silently changes what a lookback window contains: the
    same instant contributes two rows, so a declared lookback of 2 may see one day of history.
    Registration scans the whole source and refuses, naming the duplicated group as evidence.
    """
    duplicated = _parquet(
        tmp_path,
        "dup.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
             (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 999.0)
           ) AS t(available_at, instrument, close)""",
    )
    document = _write(tmp_path, "w.yaml", _dataset_document(duplicated))

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "dataset.register.key"
    failure = payload["failures"][0]
    assert failure["code"] == "dataset.register.key.duplicate"
    assert "must be unique" in failure["requirement"]
    assert failure["examples"], "the duplicated group must be shown, not merely counted"
    assert not (tmp_path / ".vqapr" / "workspace.yaml").exists(), "nothing may be written"


def test_a_column_that_does_not_exist_is_refused_against_the_real_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registration opens the file. A declaration is checked against data, not accepted on trust."""
    document = _write(
        tmp_path, "w.yaml", _dataset_document(_prices(tmp_path), fields="{close: NOT_A_COLUMN}")
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "dataset.register.schema"
    failure = payload["failures"][0]
    assert failure["code"] == "dataset.register.schema.field_missing"
    assert "NOT_A_COLUMN" in failure["requirement"]
    # The columns that do exist are the evidence a user needs to fix the declaration.
    assert "close" in failure["observed"]


def test_a_naive_available_at_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`available_at` decides what a callback may see, so it must carry a zone."""
    naive = _parquet(
        tmp_path,
        "naive.parquet",
        """SELECT * FROM (VALUES
             (TIMESTAMP '2024-03-05 03:00:00', 'A', 100.0)
           ) AS t(available_at, instrument, close)""",
    )
    document = _write(tmp_path, "w.yaml", _dataset_document(naive))

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["failures"][0]["code"].startswith("dataset.register.schema.available_at")


def test_the_first_registration_creates_the_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`register` is typed in an empty directory, so it must not require a workspace to exist."""
    document = _write(tmp_path, "w.yaml", _dataset_document(_prices(tmp_path)))

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 0, payload
    assert payload["registered"] == {"datasets": ["prices"]}


def test_a_component_declaration_resolves_its_path_beside_the_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`vqapr new` writes `path: my_alpha.py` next to `my_alpha.py`, so relative must mean that.

    Resolving against the process working directory instead would make a declaration work only
    when the user happened to stand in the right folder.
    """
    nested = tmp_path / "components"
    nested.mkdir()
    (nested / "limit.py").write_text(
        "from vqapr.public import Constraint, ConstraintBounds\n"
        "class Limit(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        "        return 'limit'\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, call):\n"
        "        return ConstraintBounds(lower_weights={}, upper_weights={})\n"
        "    def monitor(self, call, account, bounds):\n"
        "        return None\n",
        encoding="utf-8",
    )
    document = _write(
        nested.parent / "components",
        "declare.yaml",
        "components:\n  limit:\n    kind: constraint\n    path: limit.py\n    object_name: Limit\n",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 0, payload
    assert payload["registered"]["components"] == ["limit"]


def test_a_component_that_cannot_receive_the_call_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registration runs `conformance()`, so a component that cannot be called never lands."""
    (tmp_path / "broken.py").write_text(
        "from vqapr.public import Constraint, ConstraintBounds\n"
        "class Limit(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        "        return 'limit'\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, call):\n"
        "        return ConstraintBounds(lower_weights={}, upper_weights={})\n"
        "    def monitor(self, account, marks):\n"  # the contract passes four
        "        return None\n",
        encoding="utf-8",
    )
    document = _write(
        tmp_path,
        "w.yaml",
        "components:\n  limit:\n    kind: constraint\n"
        "    path: broken.py\n    object_name: Limit\n",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "component.conformance"
    assert payload["failures"][0]["code"] == "component.conformance.signature_invalid"


def test_an_unusable_declaration_key_is_refused_in_every_section_that_becomes_an_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fat-fingered YAML key must not read as the framework breaking.

    Every section here turns its key into a typed identifier, and each of those constructors
    refuses an empty or whitespace-bearing string with a bare `ValueError`. Nothing caught **four
    of the five**, so the envelope said `stage:"unhandled"` with an empty `failures[]` — the same
    shape, and the same lie, as the constraint-identity crash this slice exists to remove.
    `strategy_configs` is the exception, for the reason noted beside its entry below.

    Driven per section because the first fix covered only `components:` and red-teaming found
    `datasets:` and `execution_inputs:` still crashing. A per-handler check is a list you can be
    one short of — and the first version of this test was one short of the table that replaced it.
    """
    (tmp_path / "limit.py").write_text(_constraint_source("'limit'"), encoding="utf-8")
    sections = {
        "datasets": (
            "datasets:\n  {key}:\n    source_id: s\n    path: x.parquet\n"
            "    instrument_field: instrument\n    available_at: available_at\n"
            "    key_fields: [available_at, instrument]\n    fields: {{close: close}}\n"
        ),
        "execution_inputs": "execution_inputs:\n  {key}:\n    dataset_id: prices\n",
        "agendas": (
            "agendas:\n  {key}:\n    role: strategy_callback\n"
            '    at: "09:00"\n    timezone: Asia/Seoul\n'
        ),
        "components": (
            "components:\n  {key}:\n    kind: constraint\n"
            "    path: limit.py\n    object_name: Limit\n"
        ),
        # The fifth entry, and the one whose behaviour actually changed. For the four above, a
        # blank key used to reach the envelope as `stage:"unhandled"`. This one did not --
        # `Workspace.component()` already caught the `ValueError` and raised a structured
        # `workspace.component.lookup.invalid`. The pre-pass changes WHICH structured refusal
        # fires, to one that names the declaration key path and collects with its siblings.
        # Omitting it would leave the test one short of the table the table exists to close.
        "strategy_configs": "strategy_configs:\n  {key}:\n    agenda_id: alpha\n",
    }
    for section, template in sections.items():
        for spelling in ('"   "', '""', '" limit "'):
            document = _write(
                tmp_path, f"{section}.yaml", template.format(key=spelling)
            )
            code, payload = _cli(
                capsys, "--project-root", str(tmp_path), "register", document
            )
            assert code == 1, (section, spelling, payload)
            assert payload["stage"] == "declaration.read", (section, spelling)
            assert [failure["code"] for failure in payload["failures"]] == [
                "declaration.read.value_invalid"
            ], (section, spelling)
            assert payload["failures"][0]["source"]["key_path"] == section

    # Collected, not stopped at the first: two bad keys in two sections cost one command.
    document = _write(
        tmp_path,
        "both.yaml",
        'datasets:\n  " ":\n    source_id: s\n    path: x.parquet\n'
        "    instrument_field: i\n    available_at: a\n    key_fields: [a]\n"
        "    fields: {c: c}\n"
        'components:\n  "":\n    kind: constraint\n    path: limit.py\n'
        "    object_name: Limit\n",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert len(payload["failures"]) == 2, payload
    assert {failure["source"]["key_path"] for failure in payload["failures"]} == {
        "datasets",
        "components",
    }


def _constraint_source(returns: str) -> str:
    return (
        "from vqapr.public import Constraint, ConstraintBounds\n"
        "class Limit(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        f"        return {returns}\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, call):\n"
        "        return ConstraintBounds(lower_weights={}, upper_weights={})\n"
        "    def monitor(self, call, account, bounds):\n"
        "        return None\n"
    )


def test_a_constraint_registered_under_an_id_it_does_not_answer_to_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The crash `check` could not see, moved to the door that can.

    `SimulationFlow` has always required the loaded constraints to carry exactly the ids the run
    froze, and enforced it with a bare `ValueError`. Nothing before it looked, so `check` returned
    `ok:true` on all five phases and `run` then died with `stage: "unhandled"` and an empty
    `failures` list -- the framework reporting itself broken when the registration was wrong.

    A refusal here is worth more than a refusal at `check`, because it costs the user nothing: the
    mismatch cannot enter the workspace, so no spec can be written against it.
    """
    (tmp_path / "limit.py").write_text(_constraint_source("'limit'"), encoding="utf-8")
    document = _write(
        tmp_path,
        "w.yaml",
        "components:\n  position-cap:\n    kind: constraint\n"
        "    path: limit.py\n    object_name: Limit\n",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    failure = payload["failures"][0]
    assert failure["code"] == "component.load.constraint_id_mismatch"
    # Both strings, in the refusal itself. A reader must not have to open the file to learn which
    # two ids disagreed.
    assert "'position-cap'" in failure["observed"]
    assert "'limit'" in failure["observed"]
    assert "'limit'" in failure["fix"] and "'position-cap'" in failure["fix"]
    # Refused before anything was written: the workspace never learned this component.
    assert not (tmp_path / ".vqapr" / "workspace.yaml").exists() or "position-cap" not in (
        tmp_path / ".vqapr" / "workspace.yaml"
    ).read_text(encoding="utf-8")


def test_a_constraint_id_computed_at_runtime_is_still_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The loaded object is asked, not the source text.

    A `constraint_id` assembled at runtime is invisible to any static read of the file, so a check
    that parsed the source would pass this and leave the crash exactly where it was. Asking the
    constructed object is what makes the guard total rather than merely usual.
    """
    (tmp_path / "limit.py").write_text(
        _constraint_source("'-'.join(['position', 'cap'])"), encoding="utf-8"
    )
    document = _write(
        tmp_path,
        "w.yaml",
        "components:\n  limit:\n    kind: constraint\n"
        "    path: limit.py\n    object_name: Limit\n",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    failure = payload["failures"][0]
    assert failure["code"] == "component.load.constraint_id_mismatch"
    assert "'position-cap'" in failure["observed"], "the computed id must be reported as computed"


def test_the_shipped_no_short_registers_under_the_id_it_answers_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reported case, both halves, plus the third remedy the refusal names.

    Registering `NoShort` as `noshort` crashed the run and registering the identical file as
    `no-short` ran clean, with nothing anywhere saying why. `NoShort` takes its id as a constructor
    argument defaulting to `no-short`, so config is a real third repair and the refusal says so.
    """
    from vqapr.constraints.builtin import shipped_constraint_path

    source = shipped_constraint_path("no_short").as_posix()

    refused = _write(
        tmp_path,
        "bad.yaml",
        f"components:\n  noshort:\n    kind: constraint\n"
        f"    path: {source}\n    object_name: NoShort\n",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", refused)
    assert code == 1
    assert payload["failures"][0]["code"] == "component.load.constraint_id_mismatch"

    accepted = _write(
        tmp_path,
        "good.yaml",
        f"components:\n  no-short:\n    kind: constraint\n"
        f"    path: {source}\n    object_name: NoShort\n",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", accepted)
    assert code == 0, payload
    assert payload["registered"]["components"] == ["no-short"]

    configured = _write(
        tmp_path,
        "configured.yaml",
        f"components:\n  noshort:\n    kind: constraint\n"
        f"    path: {source}\n    object_name: NoShort\n"
        f"    config:\n      constraint_id: noshort\n",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", configured)
    assert code == 0, payload
    assert payload["registered"]["components"] == ["noshort"]


def test_a_missing_key_names_the_section_rather_than_raising_a_bare_keyerror(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`KeyError: 'available_at'` tells a user a dict lookup failed. This tells them which file."""
    document = _write(
        tmp_path,
        "w.yaml",
        "datasets:\n  prices:\n    source_id: s\n    path: p.parquet\n",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert "datasets.prices must declare" in payload["error"]
    assert "KeyError" not in payload["error"]


def test_an_unknown_section_is_named_rather_than_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo must not report success having registered nothing."""
    document = _write(tmp_path, "w.yaml", "dataset:\n  prices: {}\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "declaration.read"
    assert payload["failures"][0]["code"] == "declaration.read.unknown_section"
    assert "dataset" in payload["failures"][0]["observed"]


def test_an_agenda_must_declare_exactly_one_source_of_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both, or neither, is a question the command must not answer by guessing.

    Pinned as a *structured* failure, not merely a non-zero exit. This was an unhandled
    `ValueError`: it reached the envelope with `family: null`, an empty `failures[]`, and a
    traceback file, so the only machine-readable thing about it was the exit code.
    """
    document = _write(
        tmp_path,
        "w.yaml",
        _dataset_document(_prices(tmp_path))
        + """
agendas:
  alpha:
    role: strategy_callback
    from_dataset: prices
    sessions: ["2024-03-05"]
    at: "04:00"
    timezone: Asia/Seoul
""",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "declaration.read"
    assert payload["family"] == "DATA"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.read.key_missing"
    assert "exactly one of from_dataset or sessions" in failure["requirement"]
    # Which of the two mistakes was made, since the requirement covers both.
    assert failure["observed"] == "agendas.alpha declares both"


def test_one_refusal_names_every_key_an_agenda_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Four round trips to assemble one agenda is the friction this closes.

    Measured on a first-time reader: `role` missing, then `role` wrong, then the
    from_dataset/sessions pair, then `timezone` -- one refusal each, four register/edit/retry
    cycles, with no way to see the required set whole. `_DATASET_KEYS` had already solved exactly
    this for datasets; agendas were missed.

    The session source is checked here too, because it is the one an agenda template cannot
    express as a required key and therefore the one most likely to be discovered last.
    """
    document = _write(tmp_path, "w.yaml", 'agendas:\n  alpha:\n    at: "04:00"\n')

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "declaration.read"
    requirements = [failure["requirement"] for failure in payload["failures"]]
    assert len(requirements) == 3, requirements
    assert any("must declare role" in text for text in requirements)
    assert any("must declare timezone" in text for text in requirements)
    assert any("exactly one of from_dataset or sessions" in text for text in requirements)
    # A missing `role` names its own vocabulary; the reader's next guess is otherwise "strategy".
    role_requirement = next(text for text in requirements if "must declare role" in text)
    assert "strategy_callback" in role_requirement
    assert "valuation" in role_requirement
    assert "monitoring" in role_requirement
    # What the declaration did carry, so the reader can see the gap rather than infer it.
    assert all("declares: at" in failure["observed"] for failure in payload["failures"])


def test_a_malformed_agenda_blames_the_file_not_the_missing_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty directory is where `register` is first typed, so the first refusal must be true.

    `apply` opens the workspace lazily for exactly this reason. Passing `workspace()` rather than
    `workspace` into the agenda builder defeated it: Python evaluates the argument first, so a
    declaration with a bad agenda reported `workspace.open.missing` and sent the reader to inspect
    a directory that was fine.
    """
    document = _write(tmp_path, "w.yaml", 'agendas:\n  alpha:\n    at: "04:00"\n')

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "declaration.read", "the file is what is wrong, not the workspace"


def test_a_component_kind_that_is_not_permitted_names_the_permitted_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`kind: model` is the obvious guess and it was an unhandled `ValueError`."""
    document = _write(tmp_path, "w.yaml", "components:\n  x:\n    kind: model\n    path: x.py\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "declaration.read"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.read.value_not_permitted"
    assert failure["observed"] == "model"
    assert set(failure["examples"]) == {"datamodel", "strategy", "constraint", "exchange"}


def test_a_sessions_list_that_is_not_a_list_is_refused_with_a_stage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One date, written without brackets, is the easiest version of this mistake to make."""
    document = _write(
        tmp_path,
        "w.yaml",
        'agendas:\n  alpha:\n    role: valuation\n    sessions: "2024-03-05"\n'
        '    at: "04:00"\n    timezone: Asia/Seoul\n',
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 1
    assert payload["stage"] == "declaration.read"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.read.value_invalid"
    assert "non-empty list of dates" in failure["requirement"]


def test_every_section_is_optional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The declaration grows with the workspace instead of demanding everything at once."""
    document = _write(tmp_path, "w.yaml", "agendas: {}\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 0, payload
    assert payload["registered"] == {}
