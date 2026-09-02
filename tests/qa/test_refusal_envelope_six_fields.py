"""Every CLI refusal carries all six fields an agent is told to read.

**This docstring described a live defect that is now fixed, and said so in the present tense.** It
read: *"`InputError.as_dict()` renders exactly four fields per failure entry [...] and never
`source`, `fix`, or `explain`"*, and it cited the type at `src/vqapr/cli/inputs.py`. Both statements
are false against the current tree — `inputs.py` renders all six with a `fix` fallback, and record
`112` moved the module to `src/vqapr/inputs.py` when the refusal vocabulary went below the CLI. An
architecture review of VB002 caught the prose still arguing for a defect the assertions below no
longer find.

What the file checks now, all of it holding:

* every `InputError`-shaped refusal renders `code`, `source`, `requirement`, `observed`, `fix` and
  `explain`, with `fix` distinct from `requirement` rather than restating it;
* `VqaprError`-shaped package refusals do the same, which they always did;
* `check`'s own wrapper does not regress the contract it re-wraps into; and
* a `cli.usage` refusal from the argument parser carries the six as well, which record `114` ruled
  it must — see `test_a_usage_rejection_carries_the_six_fields_too` for why that reversed an
  earlier decision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from vqapr.cli.main import main


def _cli(
    capsys: pytest.CaptureFixture[str], project_root: Path, *argv: str
) -> tuple[int, dict[str, Any]]:
    code = main(["--project-root", str(project_root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _six_field_gaps(entry: dict[str, Any]) -> list[str]:
    """Which of the six advertised fields are missing or empty on one failure entry."""
    missing: list[str] = []
    for field in ("code", "source", "requirement", "observed", "fix", "explain"):
        required = field in ("code", "requirement", "fix", "explain")
        if field not in entry or (required and not entry[field]):
            missing.append(field)
    return missing


def test_new_missing_component_id_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`new strategy` with no positional id raises `InputError`, and the entry carries all six.

    Titled "BROKEN" while its body asserted `gaps == []`, which is the shape of a test written
    against a defect and never retitled when the defect was fixed. The assertion was always the
    truth; only the heading disagreed with it.
    """
    code, payload = _cli(capsys, tmp_path, "new", "strategy")
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.keys_missing"
    gaps = _six_field_gaps(entry)
    assert gaps == [], (
        f"expected exactly source/fix/explain missing (pin the known gap), got: {gaps}. "
        f"entry={entry}"
    )


def test_new_dataset_already_exists_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    existing = tmp_path / "run-spec.yaml"
    existing.write_text("x", encoding="utf-8")
    code, payload = _cli(capsys, tmp_path, "new", "run-spec", "--out", str(existing))
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.file_exists"
    assert _six_field_gaps(entry) == [], (
        "a CLI-level refusal must carry the same six fields a package refusal does; the envelope "
        "cannot be conditional on which layer happened to refuse"
    )


def test_register_missing_file_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _cli(capsys, tmp_path, "register", str(tmp_path / "nope.yaml"))
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.file_missing"
    assert _six_field_gaps(entry) == [], (
        "a CLI-level refusal must carry the same six fields a package refusal does; the envelope "
        "cannot be conditional on which layer happened to refuse"
    )


def test_register_non_mapping_yaml_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    code, payload = _cli(capsys, tmp_path, "register", str(bad))
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.not_a_mapping"
    assert _six_field_gaps(entry) == [], (
        "a CLI-level refusal must carry the same six fields a package refusal does; the envelope "
        "cannot be conditional on which layer happened to refuse"
    )


def test_run_missing_spec_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _cli(capsys, tmp_path, "run", str(tmp_path / "nope.yaml"))
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.file_missing"
    assert _six_field_gaps(entry) == [], (
        "a CLI-level refusal must carry the same six fields a package refusal does; the envelope "
        "cannot be conditional on which layer happened to refuse"
    )


def test_show_unknown_run_refusal_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _cli(capsys, tmp_path, "show", "run", "no-such-run-id")
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.value_invalid"
    assert _six_field_gaps(entry) == [], (
        "a CLI-level refusal must carry the same six fields a package refusal does; the envelope "
        "cannot be conditional on which layer happened to refuse"
    )


def test_check_wraps_the_same_input_error_type_into_the_full_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control case: `check`'s own `_from_input` wrapper genuinely fixes the gap FOR check.

    This proves the fix is possible (it already exists, just not shared) and that the gap
    demonstrated above is not some inherent property of `InputError` -- it is that only one of
    five commands bothers to re-wrap it.
    """
    code, payload = _cli(capsys, tmp_path, "check", str(tmp_path / "nope.yaml"))
    assert code == 1
    entry = payload["failures"][0]
    assert entry["code"] == "cli.input.file_missing"
    gaps = _six_field_gaps(entry)
    assert gaps == [], f"check's own InputError wrapper regressed the six-field contract: {gaps}"
    assert entry["fix"].strip() != entry["requirement"].strip()


def test_register_conflict_refusal_a_real_vqaprerror_carries_all_six_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The positive control: once a refusal comes from the PACKAGE (VqaprError, past the
    file-reading stage), all six fields are present and fix != requirement. This isolates the
    defect above to InputError's own rendering rather than a general envelope problem.
    """
    prices_dir = tmp_path / "prepared" / "prices"
    prices_dir.mkdir(parents=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-01-02 00:00:00+00', 'A', 100.0)
              ) AS t(available_at, instrument, close))
              TO '{(prices_dir / "d.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    decl = tmp_path / "dataset.yaml"
    decl.write_text(
        f"""
datasets:
  prices:
    source_id: price-source
    path: {prices_dir.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields: {{close: close}}
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, tmp_path, "register", str(decl))
    assert code == 0, payload

    conflicting = tmp_path / "dataset-conflict.yaml"
    conflicting.write_text(
        f"""
datasets:
  prices:
    source_id: price-source
    path: {prices_dir.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: rows
    key_fields: [instrument]
    fields: {{close: close, open: close}}
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, tmp_path, "register", str(conflicting))
    assert code == 1, payload
    entry = payload["failures"][0]
    assert entry["code"] == "workspace.dataset.register.conflict"
    gaps = _six_field_gaps(entry)
    assert gaps == [], f"a real package refusal is missing fields: {gaps}"
    assert entry["fix"].strip() != entry["requirement"].strip()


def test_a_usage_rejection_carries_the_six_fields_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`docs/issues/030`, second half, settled by record `114` — and this test used to assert the
    opposite.

    It asserted `fix`, `source` and `explain` were absent "by design", on the reasoning that usage
    rejections "never claimed the six-field contract in the first place". **That reasoning was
    checkable and false.** `SKILL.md` claims it unconditionally — *"Every entry carries `code`,
    `source`, `requirement`, `observed`, `fix` and `explain`"* — and then tells the reader to read
    `fix` first. So the document and this test disagreed, which is exactly what issue 030 reopened
    for a ruling rather than leaving to whichever a reader happened to find.

    **The ruling is that `cli.usage` is inside the guarantee.** A bad argument is the first refusal
    a new user ever sees, and it was the one refusal with no `fix` to read. An exception carved at
    the most common entry point is not an exception, it is the guarantee not holding. The three
    keys cost nothing to add and `fix` is genuinely actionable.

    `source` and `explain` are `null`, not absent: argparse rejected the command line, so there is
    no file to point at and no package concept to explain. `SKILL.md` already permitted a null
    location and now names this case.
    """
    code, payload = _cli(capsys, tmp_path, "list", "nonsense-kind")
    assert code == 1
    assert payload["stage"] == "cli.usage"

    entry = payload["failures"][0]
    assert entry["code"] == "cli.usage.rejected"
    for field in ("code", "source", "requirement", "observed", "fix", "explain"):
        assert field in entry, f"the six-field guarantee is missing {field!r} on a usage refusal"

    assert entry["fix"], "the field SKILL.md tells a reader to read first must not be empty"
    assert "--help" in entry["fix"], "the fix must name an action, not restate the problem"
    assert entry["fix"] != entry["requirement"]
    # An OBJECT with null members, not a bare null. Every other refusal emits an object, so a
    # reader doing `failure["source"]["file"]` would hit a TypeError on this refusal alone --
    # which is the field-type uniformity an architecture review of VB002 caught being broken.
    assert entry["source"] == {"file": None, "key_path": None, "line": None}, (
        "a rejected command line has no location, but it must say so in the shape every other "
        "refusal uses"
    )
    assert entry["explain"] is None, "and no package concept to explain"

    # `family` stays None, which is a different question and unchanged: FailureFamily is a closed
    # set of PACKAGE stages, and this failure reached none of them.
    assert payload["family"] is None
