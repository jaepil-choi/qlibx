"""Adversarial attack on claim 5: quarantine, not failure, for a legacy dataset registration.

`tests/test_workspace.py` already exercises this at the library level (`Workspace.open` still
works, `dataset.register.span.absent` fires at use, the advertised repair command runs). This
file's job is to attack the properties that file does NOT prove:

- The repair is driven through the actual CLI (`vqapr register <file>`), exactly as the refusal's
  own `retry_precondition` text instructs an agent to do -- not `Workspace.register_dataset`
  called directly from a test.
- TWO stale entries at once, and repairing ONE must not disturb the OTHER still-stale one, nor
  the one healthy registration sitting alongside them.
- `list datasets` enumerates a quarantined entry through the CLI surface too (not just the
  `Workspace.datasets` property), since an agent's actual view of the workspace is the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from vqapr.cli.main import main
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.public import register_dataset as pub_register_dataset
from vqapr.workspace import Workspace


def _cli(
    capsys: pytest.CaptureFixture[str], project_root: Path, *argv: str
) -> tuple[int, dict[str, Any]]:
    code = main(["--project-root", str(project_root), *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _make_legacy(workspace: Workspace, count: int) -> None:
    """Strip the `span:` block from the first `count` registrations, in registration order.

    Reproduces the exact legacy shape the migration path is meant to admit: five keys, no
    `span`. Copied from `tests/test_workspace.py::_make_legacy`.
    """
    kept: list[str] = []
    dropping = False
    stripped = 0
    for line in workspace.path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "span:" and stripped < count:
            dropping = True
            stripped += 1
            continue
        if dropping:
            if line.lstrip().startswith("- '"):
                continue
            dropping = False
        kept.append(line)
    assert stripped == count, "the fixture did not strip the spans it meant to"
    workspace.path.write_text("\n".join(kept) + "\n", encoding="utf-8")


@pytest.fixture
def two_stale_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace holding alpha, beta, gamma; alpha and beta quarantined, gamma healthy."""
    prices_dir = tmp_path / "prepared" / "prices"
    prices_dir.mkdir(parents=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-01-02 00:00:00+00', 'A', 100.0, DATE '2024-01-02', 10.0),
                (TIMESTAMPTZ '2024-01-03 00:00:00+00', 'A', 101.0, DATE '2024-01-03', 11.0)
              ) AS t(available_at, instrument, close, session_date, open))
              TO '{(prices_dir / "d.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    def registration(raw_id: str) -> DatasetRegistration:
        return DatasetRegistration.of(
            raw_id,
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="rows",
            key_fields=("session_date", "instrument"),
            fields={"close": "close", "session_date": "session_date"},
        )

    for name in ("alpha", "beta", "gamma"):
        pub_register_dataset(tmp_path, registration(name), SourceSpec.of("prices", prices_dir))

    ws = Workspace.open(tmp_path)
    _make_legacy(ws, 2)  # alpha, beta quarantined (registration order); gamma stays healthy
    return tmp_path, prices_dir


def test_workspace_open_and_list_survive_two_stale_entries(
    two_stale_workspace: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = two_stale_workspace

    reopened = Workspace.open(root)
    assert sorted(str(item.dataset_id) for item in reopened.datasets) == ["alpha", "beta", "gamma"]

    code, payload = _cli(capsys, root, "list", "datasets")
    assert code == 0, payload
    listed_ids = sorted(item["dataset_id"] for item in payload["items"])
    assert listed_ids == ["alpha", "beta", "gamma"], (
        "the CLI's own `list datasets` must enumerate quarantined registrations too, not just "
        "the library-level Workspace.datasets property"
    )


def test_using_either_stale_entry_by_name_refuses(two_stale_workspace: tuple[Path, Path]) -> None:
    root, _ = two_stale_workspace
    reopened = Workspace.open(root)

    for name in ("alpha", "beta"):
        with pytest.raises(VqaprError) as refused:
            reopened.dataset(name)
        assert refused.value.failures[0].code == "dataset.register.span.absent"
        assert name in (refused.value.failures[0].observed or "")

    # The healthy neighbour is untouched by either quarantine.
    assert reopened.span("gamma") is not None


def test_the_advertised_repair_command_runs_through_the_real_cli_and_spares_the_others(
    two_stale_workspace: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The property the whole quarantine design exists for, driven exactly as an agent would.

    Repairs `alpha` via `vqapr register <declaration.yaml>` -- the literal command named in the
    refusal's `retry_precondition` -- and checks `beta` (still stale) and `gamma` (never stale)
    are both untouched by the repair.
    """
    root, prices_dir = two_stale_workspace
    reopened = Workspace.open(root)

    with pytest.raises(VqaprError) as refused:
        reopened.dataset("alpha")
    assert "vqapr register <declaration.yaml>" in (refused.value.retry_precondition or "")

    declaration = root / "repair-alpha.yaml"
    declaration.write_text(
        f"""
datasets:
  alpha:
    source_id: prices
    path: {prices_dir.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: rows
    key_fields: [session_date, instrument]
    fields: {{close: close, session_date: session_date}}
""",
        encoding="utf-8",
    )

    code, payload = _cli(capsys, root, "register", str(declaration))
    assert code == 0, payload

    repaired = Workspace.open(root)
    assert repaired.span("alpha") is not None, "alpha should carry a real measured span now"

    # beta is STILL quarantined -- the repair of alpha must not have touched it.
    with pytest.raises(VqaprError) as still_stale:
        repaired.dataset("beta")
    assert still_stale.value.failures[0].code == "dataset.register.span.absent"

    # gamma was never quarantined and must be untouched by alpha's repair.
    gamma_span_after = repaired.span("gamma")
    gamma_span_before = Workspace.open(root).span("gamma")
    assert gamma_span_after == gamma_span_before

    listed = _cli(capsys, root, "list", "datasets")[1]["items"]
    listed_ids = sorted(item["dataset_id"] for item in listed)
    assert listed_ids == ["alpha", "beta", "gamma"], (
        "beta must remain enumerable after alpha's repair"
    )


def test_repairing_a_quarantined_registration_cannot_smuggle_a_declaration_change(
    two_stale_workspace: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Repairing the span must not be usable as cover for redefining what the dataset means."""
    root, prices_dir = two_stale_workspace

    declaration = root / "repair-alpha-changed.yaml"
    declaration.write_text(
        f"""
datasets:
  alpha:
    source_id: prices
    path: {prices_dir.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: rows
    key_fields: [session_date, instrument]
    fields: {{close: open, session_date: session_date}}
""",
        encoding="utf-8",
    )

    code, payload = _cli(capsys, root, "register", str(declaration))
    assert code == 1, payload
    codes = {f["code"] for f in payload["failures"]}
    assert "workspace.dataset.register.conflict" in codes, (
        f"a changed declaration under cover of a span repair was not refused: {codes}"
    )
