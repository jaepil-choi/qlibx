"""`vqapr new instruments` emits a runnable script and the declaration that registers its output.

Two files, following the `new exchange` precedent. Emitting only the YAML would leave an author to
discover the four category names from a refusal, which is the stall `new exchange` exists to
remove: an author guessed six times at a type no template, help text or skill section ever named.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vqapr.cli.new import run as new_run
from vqapr.cli.register import run as register_run
from vqapr.workspace import Workspace

KINDS = ("stock", "etf", "index", "factor")


def _emit(root: Path, **overrides: object) -> dict:
    settings: dict[str, object] = {
        "kind": "instruments",
        "out": None,
        "component_id": None,
        "instruments": None,
    }
    settings.update(overrides)
    return new_run(argparse.Namespace(**settings), project_root=root)


def test_it_emits_both_the_script_and_its_declaration(tmp_path: Path) -> None:
    emitted = _emit(tmp_path)

    assert Path(emitted["path"]).name == "instruments.py"
    assert Path(emitted["declaration"]).name == "instruments.yaml"
    assert Path(emitted["path"]).is_file()
    assert Path(emitted["declaration"]).is_file()


def test_the_declaration_names_every_shipped_category(tmp_path: Path) -> None:
    """The whole closed vocabulary, so the author never has to look it up.

    Unused ones are commented rather than omitted: an author who needs `etf` should find the word
    already written, not have to learn it exists.
    """
    emitted = _emit(tmp_path)
    body = Path(emitted["declaration"]).read_text(encoding="utf-8")

    for kind in KINDS:
        assert f"{kind}: instruments_{kind}.parquet" in body


def test_the_script_names_the_categories_and_says_why_they_matter(tmp_path: Path) -> None:
    """Discoverability is the whole reason this template exists."""
    emitted = _emit(tmp_path)
    body = Path(emitted["path"]).read_text(encoding="utf-8")

    for kind in KINDS:
        assert kind in body
    # The consequence, not just the vocabulary. An author who does not know why the category
    # matters has no reason to think about it.
    assert "sale tax" in body


def test_the_emitted_script_runs_unedited_and_its_output_registers(tmp_path: Path) -> None:
    """The whole loop: emit, run, register -- with no edit in between.

    A template that does not run as emitted teaches its author to distrust it, and the first thing
    they do is delete the parts they do not understand.
    """
    Workspace.create(tmp_path)
    emitted = _emit(tmp_path)

    completed = subprocess.run(
        [sys.executable, emitted["path"]], capture_output=True, text=True, cwd=tmp_path
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "instruments_stock.parquet").is_file()

    registered = register_run(
        argparse.Namespace(declaration=emitted["declaration"]), project_root=tmp_path
    )
    receipt = registered["registered"]["instruments"][0]
    assert receipt["by_kind"] == {"stock": 2}


def test_the_script_prints_the_command_that_comes_next(tmp_path: Path) -> None:
    """A step that ends without naming the next one is where a first run stalls."""
    Workspace.create(tmp_path)
    emitted = _emit(tmp_path)

    completed = subprocess.run(
        [sys.executable, emitted["path"]], capture_output=True, text=True, cwd=tmp_path
    )

    assert "vqapr register instruments.yaml" in completed.stdout


def test_it_refuses_to_overwrite_either_file(tmp_path: Path) -> None:
    _emit(tmp_path)

    with pytest.raises(Exception):
        _emit(tmp_path)


def test_the_roster_id_is_the_authors_to_choose(tmp_path: Path) -> None:
    emitted = _emit(tmp_path, component_id="krx-universe")

    body = Path(emitted["declaration"]).read_text(encoding="utf-8")
    assert "krx-universe:" in body


def test_a_supplied_universe_reaches_the_emitted_script(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    emitted = _emit(tmp_path, instruments=["A", "B", "C"])

    body = Path(emitted["path"]).read_text(encoding="utf-8")
    for name in ("A", "B", "C"):
        assert f"'{name}'" in body

    completed = subprocess.run(
        [sys.executable, emitted["path"]], capture_output=True, text=True, cwd=tmp_path
    )
    assert completed.returncode == 0, completed.stderr
    registered = register_run(
        argparse.Namespace(declaration=emitted["declaration"]), project_root=tmp_path
    )
    assert registered["registered"]["instruments"][0]["instruments"] == 3


def test_the_emitted_declaration_is_valid_yaml(tmp_path: Path) -> None:
    import yaml

    emitted = _emit(tmp_path)
    document = yaml.safe_load(Path(emitted["declaration"]).read_text(encoding="utf-8"))

    assert list(document) == ["instruments"]
    tables = document["instruments"]["universe"]["tables"]
    assert tables == {"stock": "instruments_stock.parquet"}, (
        "only the categories this universe uses may be live; the rest stay commented"
    )
    assert json.dumps(document)  # round-trips cleanly
