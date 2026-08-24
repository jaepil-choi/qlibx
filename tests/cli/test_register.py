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
        "    def project(self, window, instruments):\n"
        "        return ConstraintBounds({}, {})\n"
        "    def validate_intended(self, intent, bounds):\n"
        "        return None\n"
        "    def evaluate(self, window, account, marks, bounds):\n"
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
        "    def project(self, window, instruments):\n"
        "        return ConstraintBounds({}, {})\n"
        "    def validate_intended(self, intent, bounds):\n"
        "        return None\n"
        "    def evaluate(self, account, marks):\n"  # the contract passes four
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
    """Both, or neither, is a question the command must not answer by guessing."""
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
    assert "exactly one of from_dataset or sessions" in payload["error"]


def test_every_section_is_optional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The declaration grows with the workspace instead of demanding everything at once."""
    document = _write(tmp_path, "w.yaml", "agendas: {}\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", document)

    assert code == 0, payload
    assert payload["registered"] == {}
