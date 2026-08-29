"""The instrument roster: exported by the user, validated by the framework, read by every run.

A category answers no to both axes canon 2.8 splits an instrument's facts along, so it belongs to
the project rather than to any venue. These pin the registration half: what the framework accepts,
what it refuses, and the receipt that makes an unconsidered universe visible.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.cli.inputs import InputError
from vqapr.cli.register import run as register_run
from vqapr.domain.instruments import InstrumentKind
from vqapr.domain.roster import build_roster
from vqapr.domain.roster_export import export_roster, read_roster_table
from vqapr.workspace import Workspace

UNIVERSE = {"A005930": "stock", "A000660": "stock", "A069500": "etf"}


def _declare(root: Path, tables: dict[str, Path]) -> Path:
    # No id above `tables:`. A project holds one roster slot and stores no id, so the level that
    # used to sit here declared an identity nothing kept.
    lines = ["instruments:", "  tables:"]
    for kind, path in sorted(tables.items()):
        lines.append(f"    {kind}: {path.relative_to(root).as_posix()}")
    declaration = root / "instruments.yaml"
    declaration.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return declaration


def _register(root: Path, declaration: Path) -> dict:
    return register_run(argparse.Namespace(declaration=str(declaration)), project_root=root)


# --- the exporter ------------------------------------------------------------------------


def test_export_writes_one_table_per_declared_kind(tmp_path: Path) -> None:
    """One parquet per category, because a parquet file carries exactly one schema.

    A single table would need a nullable column for every attribute any category might carry, and
    a null would then mean both "not applicable here" and "the author forgot" -- the ambiguity
    this package refuses everywhere else.
    """
    written = export_roster(UNIVERSE, tmp_path)

    assert sorted(written) == ["etf", "stock"]
    assert read_roster_table(written["stock"]) == {"A005930": "stock", "A000660": "stock"}
    assert read_roster_table(written["etf"]) == {"A069500": "etf"}


def test_export_is_byte_identical_for_an_unchanged_universe(tmp_path: Path) -> None:
    """A digest that moved because a dict iterated differently would report a change nobody made."""
    first = export_roster(UNIVERSE, tmp_path / "a")
    second = export_roster(dict(reversed(list(UNIVERSE.items()))), tmp_path / "b")

    for kind, path in first.items():
        assert path.read_bytes() == second[kind].read_bytes()


def test_export_refuses_a_kind_outside_the_closed_vocabulary(tmp_path: Path) -> None:
    """`InstrumentKind` stays closed and package-owned.

    A user-invented category would be one no venue has terms for, and expansion is a membership
    test -- so it would silently drop its instruments out of the venue rather than refusing.
    """
    with pytest.raises(ValueError, match="unknown instrument kind"):
        export_roster({"A005930": "commonstock"}, tmp_path)


def test_export_writes_nothing_for_an_unused_category(tmp_path: Path) -> None:
    written = export_roster({"A005930": "stock"}, tmp_path)

    assert sorted(written) == ["stock"]
    assert not (tmp_path / "instruments_etf.parquet").exists()


# --- resolution --------------------------------------------------------------------------


def test_the_table_key_and_the_kind_column_must_agree(tmp_path: Path) -> None:
    """Why the redundant `kind` column is worth carrying.

    The declaration already states the category via its key, so the column adds nothing a reader
    needs. It exists so registration can check the two against each other, which catches a table
    pointed at the wrong key before it charges the wrong rate for the life of the project.
    """
    with pytest.raises(ValueError, match="table key and the column must agree"):
        build_roster({"etf": {"A005930": "stock"}})


def test_one_instrument_has_exactly_one_category(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="declared more than once"):
        build_roster({"stock": {"A005930": "stock"}, "etf": {"A005930": "etf"}})


def test_an_undeclared_id_raises_rather_than_becoming_a_share(tmp_path: Path) -> None:
    """The defect the whole design exists to remove.

    An id nobody described must not silently acquire share treatment. Defaulting would be *"the
    defect itself, written down rather than inferred -- worse than the status quo, because it
    looks like a declaration."*
    """
    roster = build_roster({"stock": {"A005930": "stock"}})

    assert roster.declares("A005930")
    assert not roster.declares("A069500")
    with pytest.raises(KeyError, match="no registered instrument describes"):
        roster.kind("A069500")


def test_sizing_routes_through_the_declared_instrument(tmp_path: Path) -> None:
    """`notional` and `quantity_for` are the inverse pair every money-to-quantity step uses.

    Routed through the instrument so a category whose contract is not one unit of the quoted price
    changes both numbers by overriding two methods, rather than by editing order planning.
    """
    roster = build_roster({"stock": {"A005930": "stock"}})

    assert roster.notional("A005930", Decimal("10"), Decimal("70000")) == Decimal("700000")
    assert roster.quantity_for("A005930", Decimal("700000"), Decimal("70000")) == Decimal("10")
    assert roster.kind("A005930") is InstrumentKind.STOCK


# --- registration ------------------------------------------------------------------------


def test_registration_reports_a_per_category_receipt(tmp_path: Path) -> None:
    """The one MECHANICAL guard against a mechanical sweep, and it fires on the SUCCESS path.

    An author who declared 2,143 names and is shown a single bucket has been told at registration
    that their universe is uniform. The same fact in a later refusal teaches far less, because by
    then it is a problem to route around rather than a number to check.
    """
    Workspace.create(tmp_path)
    written = export_roster(UNIVERSE, tmp_path / "data")

    result = _register(tmp_path, _declare(tmp_path, written))

    receipt = result["registered"]["instruments"][0]
    assert receipt["instruments"] == 3
    assert receipt["by_kind"] == {"etf": 1, "stock": 2}


def test_a_uniform_universe_still_reports_its_one_bucket(tmp_path: Path) -> None:
    """Omitting it would hide exactly the case the receipt exists to expose."""
    Workspace.create(tmp_path)
    written = export_roster({"A": "stock", "B": "stock"}, tmp_path / "data")

    result = _register(tmp_path, _declare(tmp_path, written))

    assert result["registered"]["instruments"][0]["by_kind"] == {"stock": 2}


def test_registration_stores_a_pointer_and_a_digest_not_a_copy(tmp_path: Path) -> None:
    """Issue 009: the roster is read fresh at run start and its digest is stated, never compared.

    A frozen copy would make an ordinary event -- a daily batch listing one new ticker -- cost a
    command every morning.
    """
    Workspace.create(tmp_path)
    written = export_roster(UNIVERSE, tmp_path / "data")
    _register(tmp_path, _declare(tmp_path, written))

    pointer = Workspace.open(tmp_path).registered_instruments()
    assert pointer is not None
    assert pointer["schema"] == "vqapr.instruments/v1"
    assert sorted(pointer["tables"]) == ["etf", "stock"]
    assert len(pointer["digest"]) == 64


def test_re_registering_a_corrected_roster_is_ordinary(tmp_path: Path) -> None:
    """Unlike a dataset, whose immutability protects provenance.

    "069500 is an ETF" is a correction about the world, and what a past run treated an instrument
    as is testified to by that run's own fills rather than by the current roster.
    """
    Workspace.create(tmp_path)
    first = export_roster({"A069500": "stock"}, tmp_path / "data")
    _register(tmp_path, _declare(tmp_path, first))
    before = Workspace.open(tmp_path).registered_instruments()

    corrected = export_roster({"A069500": "etf"}, tmp_path / "data")
    result = _register(tmp_path, _declare(tmp_path, corrected))

    after = Workspace.open(tmp_path).registered_instruments()
    assert result["registered"]["instruments"][0]["by_kind"] == {"etf": 1}
    assert after["digest"] != before["digest"], "the digest must follow the corrected file"


def test_registration_refuses_a_table_it_cannot_read(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    (tmp_path / "data").mkdir()
    declaration = tmp_path / "instruments.yaml"
    declaration.write_text(
        "instruments:\n  tables:\n    stock: data/absent.parquet\n", encoding="utf-8"
    )

    with pytest.raises(InputError, match="readable instrument table"):
        _register(tmp_path, declaration)


def test_an_unsupported_kind_in_a_hand_written_table_is_refused_by_instrument_and_file(
    tmp_path: Path,
) -> None:
    """`instruments.py` cannot produce this; a hand-written or hand-edited parquet can.

    The exporter only ever writes the four package-owned kinds, so an unsupported one arrives
    exactly one way: someone wrote the parquet directly, or edited the exporter's output. That is a
    legitimate input -- producing a clean table is the author's job, refusing a dirty one is
    registration's -- and it must not reach a run, because `InstrumentKind` is closed and a venue
    has no terms for a category outside it.

    What matters here is that the refusal is findable. Reporting only `unknown instrument kind
    'crypto'` tells an author of a three-thousand-row roster what is wrong and not where, and a
    roster is precisely the artifact where locating the row by hand is the expensive part.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    Workspace.create(tmp_path)
    (tmp_path / "data").mkdir()
    table = tmp_path / "data" / "instruments_stock.parquet"
    pq.write_table(
        pa.table({"instrument_id": ["A005930", "BTCUSD"], "kind": ["stock", "crypto"]}), table
    )
    declaration = _declare(tmp_path, {"stock": table})

    with pytest.raises(InputError) as refused:
        _register(tmp_path, declaration)

    observed = refused.value.observed
    assert "BTCUSD" in observed, "the offending instrument must be named, not just its kind"
    assert "crypto" in observed
    assert "etf, factor, index, stock" in observed, "the legal vocabulary must be listed"
    assert table.name in observed, "the file to open must be named"
    # The remedy names the tool that cannot produce this input, which is the shortest route back
    # to a clean table for an author who edited one by hand.
    assert "instruments.py" in refused.value.fix


def test_registration_names_a_table_sitting_beside_the_declaration_and_undeclared(
    tmp_path: Path,
) -> None:
    """The emitted template ships one category live and the rest commented.

    An author who exports twelve names across two categories and registers it unchanged registers
    ten, silently, with the ETF table sitting beside the declaration undeclared. The per-category
    receipt made that legible only to a reader who noticed that `{"stock": 10}` was short of a
    universe of twelve.

    Reported rather than refused: declaring a subset is legitimate -- a project may export every
    category its exporter knows and trade only equities -- so this names the file and leaves the
    decision with the author.
    """
    Workspace.create(tmp_path)
    written = export_roster(UNIVERSE, tmp_path / "data")
    assert set(written) == {"stock", "etf"}, "the fixture universe must span two categories"

    declaration = _declare(tmp_path, {"stock": written["stock"]})
    receipt = _register(tmp_path, declaration)["registered"]["instruments"][0]

    assert receipt["by_kind"] == {"stock": 2}
    assert receipt["undeclared"] == [written["etf"].name]
    assert "etf" in written["etf"].name, "the receipt must name the file, not the category alone"

    # Declaring both leaves nothing to report, so the field is absent rather than empty: a reader
    # testing for it should not have to distinguish "none found" from "not looked for".
    complete = _register(tmp_path, _declare(tmp_path, written))["registered"]["instruments"][0]
    assert "undeclared" not in complete
    assert complete["by_kind"] == {"stock": 2, "etf": 1}


def test_registration_refuses_the_old_id_keyed_declaration(tmp_path: Path) -> None:
    """One roster per project, and now no name for it either.

    The old shape put an id above `tables:`. The workspace stores `schema`, `tables` and `digest`
    and no id, so that name was echoed back in the receipt and discarded -- and declaring a second
    one silently replaced the first. Two rosters would also require asking *which roster knows this
    id*, which is a matcher, the thing this package removed from the charge path on purpose.

    Refused outright rather than accepted with the id ignored: accepting it would be a
    compatibility shim for a statement that was never true.
    """
    Workspace.create(tmp_path)
    written = export_roster(UNIVERSE, tmp_path / "data")
    declaration = tmp_path / "instruments.yaml"
    body = ["instruments:", "  krx:", "    tables:"]
    for kind, path in sorted(written.items()):
        body.append(f"      {kind}: {path.relative_to(tmp_path).as_posix()}")
    declaration.write_text("\n".join(body) + "\n", encoding="utf-8")

    with pytest.raises(InputError, match="no id above them") as error:
        _register(tmp_path, declaration)
    # Names what was found and what to do, so a reader does not have to diff against a re-emitted
    # template to see that one line must go.
    assert "krx" in error.value.observed
    assert "lift `tables:` up one level" in error.value.fix


def test_a_table_missing_its_columns_is_refused_by_name(tmp_path: Path) -> None:
    """Registration trusts nothing, because a hand-written table is a legitimate input."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    Workspace.create(tmp_path)
    (tmp_path / "data").mkdir()
    path = tmp_path / "data" / "wrong.parquet"
    pq.write_table(pa.table({"ticker": ["A005930"]}), path)
    declaration = tmp_path / "instruments.yaml"
    declaration.write_text(
        "instruments:\n  tables:\n    stock: data/wrong.parquet\n", encoding="utf-8"
    )

    with pytest.raises(InputError) as error:
        _register(tmp_path, declaration)
    # The missing column is named in `observed`, which is the field a reader is shown. A refusal
    # saying only "unreadable" would send them opening the file to find out what it lacked.
    assert "instrument_id" in error.value.observed
