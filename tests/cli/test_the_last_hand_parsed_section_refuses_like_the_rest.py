"""`instruments:` refuses a misspelled key the way every other section does.

One-shape campaign Step 5 (M5b). Every declaration section's key set is a pydantic model and its
refusals come out of `declarations.refusals_from` -- except `instruments:`, which read `tables`
with the hand-written `_require_keys` and then took whatever mapping it found. So a typo under
`instruments:` fell through to the refusal written for the RETIRED `instruments: {<id>: {tables:
...}}` shape, and that refusal's `fix` told the reader to *"remove the id line and lift `tables:`
up one level"* -- advice for a mistake they had not made.

The retired-shape refusal is still there and still right for the shape it names; what changed is
that it is narrowed to that shape, and anything else is answered by the permitted key set and the
nearest spelling, which is what `019` and `017` bought for every other section.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.main import main
from vqapr.domain.instruments import export_roster


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _tables(tmp_path: Path) -> dict[str, str]:
    written = export_roster({"A005930": "stock"}, tmp_path / "roster")
    return {
        kind: table.relative_to(tmp_path).as_posix() for kind, table in sorted(written.items())
    }


def _declaration(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "roster.yaml"
    path.write_text("instruments:\n" + body, encoding="utf-8")
    return path


def test_a_misspelled_key_names_the_permitted_set_and_the_nearest_spelling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "  tabels:\n" + "".join(
        f"    {kind}: {path}\n" for kind, path in _tables(tmp_path).items()
    )

    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "register", str(_declaration(tmp_path, body))
    )

    assert code != 0
    # Both facts, in one round trip: the key that is not one of ours, and the one that is
    # missing. That is what `refusals_from` promises every other section.
    by_code = {failure["code"]: failure for failure in refused["failures"]}
    assert set(by_code) == {"declaration.read.key_unknown", "declaration.read.key_missing"}

    unknown = by_code["declaration.read.key_unknown"]
    assert unknown["requirement"] == "instruments may declare: tables"
    assert "'tabels'" in unknown["observed"]
    assert "tables" in unknown["fix"], "the nearest spelling, which the typist cannot see"
    assert unknown["source"]["key_path"] == "instruments.tabels"

    for failure in refused["failures"]:
        assert "lift" not in failure["fix"], "not the retired-shape advice for a mistake not made"


def test_the_retired_shape_still_gets_the_refusal_written_for_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`instruments: {<id>: {tables: ...}}`, narrowed to the shape it names."""
    body = "  krx:\n    tables:\n" + "".join(
        f"      {kind}: {path}\n" for kind, path in _tables(tmp_path).items()
    )

    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "register", str(_declaration(tmp_path, body))
    )

    assert code != 0
    (failure,) = refused["failures"]
    assert "maps to krx rather than to `tables`" in failure["observed"]
    assert "lift `tables:` up one level" in failure["fix"]


def test_the_declared_shape_still_registers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "  tables:\n" + "".join(
        f"    {kind}: {path}\n" for kind, path in _tables(tmp_path).items()
    )

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", str(_declaration(tmp_path, body))
    )

    assert code == 0, registered
    assert registered["registered"]["instruments"], "the roster receipt, as before"
