"""Adversarial attack on claim 8: every refusal carries `code, source, requirement, observed,
fix, explain`, and `fix` is not the `requirement` restated.

`tests/characterization/test_fix_is_not_a_restatement.py` already sweeps every `Failure.bounded`
CALL SITE statically via AST -- but that sweep only ever looks at `Failure.bounded(...)`
constructions. It cannot see what actually reaches stdout through a DIFFERENT refusal type. This
file provokes real refusals through the live CLI (`new`, `register`, `check`, `run`, `list`,
`show`) and asserts the six-field contract on what an agent actually parses.

**held: every CLI refusal now carries all six.** `InputError`
(`src/vqapr/cli/inputs.py`) is the type every one of `new`,
`register`, `run`, and `show`'s own-file input refusals raise (missing file, non-YAML, already
exists, missing required key, invalid value). `InputError.as_dict()` renders exactly four fields
per failure entry -- `code`, `requirement`, `observed`, `examples`/`example_total` -- and never
`source`, `fix`, or `explain`. Only `vqapr.cli.check._from_input` re-wraps an `InputError` into
the full six-field shape, and it does so ONLY for the `check` verb. Every other command's own-file
refusals ship claim 8's advertised envelope with half the fields missing.

This is confirmed against the package's OWN failures (`VqaprError`, raised from `register`/`run`
once past the file-reading stage) which DO carry all six fields -- so the gap is specifically
`InputError`'s rendering, not a general envelope problem.
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
    """BROKEN: `new strategy` with no positional id raises InputError; the envelope entry is
    missing `source`, `fix`, and `explain` entirely.
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


def test_list_unknown_kind_is_a_usage_shape_with_no_failure_fields_by_design(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A usage error (bad argparse choice) is rendered through a wholly different shape --
    `cli.usage.rejected` -- with no `family` and a single `error` string, not a `Failure` list at
    all. This is by design (`vqapr.cli.envelope.UsageError`) and is asserted here so claim 8's
    scope is pinned precisely: it applies to `Failure`-shaped and `InputError`-shaped refusals,
    not to usage rejections, which never claimed the six-field contract in the first place.
    """
    code, payload = _cli(capsys, tmp_path, "list", "nonsense-kind")
    assert code == 1
    assert payload["stage"] == "cli.usage"
    entry = payload["failures"][0]
    assert entry["code"] == "cli.usage.rejected"
    assert "fix" not in entry
    assert "source" not in entry
    assert "explain" not in entry
