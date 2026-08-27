"""`store` is defined once, and every rule about it is read from that definition.

AC-R2 says the run spec carries `store`, and that `store` has exactly `root` and `tables`. AC-P3
then says an empty `tables` leaves a run record and no dataset, and a non-empty one makes each
named table a dataset -- which reads like a second rule and is really a consequence of the first.

The way to keep it a consequence is structural: these tests import `StoreSpec` and read
`declares_dataset_tables` rather than restating the key names or re-deriving the emptiness rule. A
divergence between the definition and the assertion then becomes a type error rather than a drift
nobody notices, which is what AC-X4' asks for in place of the ungreppable "no second normative
definition".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.flow.store_spec import STORE_KEYS, StoreSpec


def test_the_key_set_is_named_once_and_read_from_there() -> None:
    """AC-X4' condition (a): exactly one place owns the keys."""
    assert STORE_KEYS == ("root", "tables")
    # The dataclass fields ARE the key set. Asserting them against each other is what makes a
    # field added in one place and forgotten in the other impossible rather than merely unlikely.
    assert {field for field in StoreSpec.__dataclass_fields__} == set(STORE_KEYS)


def test_an_absent_store_block_is_a_complete_answer() -> None:
    """Most specs declare no store, and that must not be an error or a special case."""
    spec = StoreSpec.of(None, base=Path("/project"))

    assert spec.root is None
    assert spec.tables == ()
    assert spec.declares_dataset_tables is False


def test_an_empty_tables_list_publishes_no_dataset(tmp_path: Path) -> None:
    """AC-P3, first half, read through the definition rather than restated.

    The rule is not "if the list is empty then skip publishing" written at each call site; it is
    what `store.tables` MEANS, asked through one property.
    """
    spec = StoreSpec.of({"tables": []}, base=tmp_path)

    assert spec.declares_dataset_tables is False


def test_a_declared_table_asks_to_become_a_dataset(tmp_path: Path) -> None:
    """AC-P3's parsing half, and only that half.

    This asserts what the DECLARATION says, which is all `StoreSpec` decides. It deliberately does
    not assert that a dataset exists, because nothing in the `vqapr run` path yet publishes one --
    and a test named `becomes_a_dataset` that only checks a parsed boolean would read as coverage
    for a behaviour nobody wrote.
    """
    spec = StoreSpec.of({"tables": ["allocation"]}, base=tmp_path)

    assert spec.declares_dataset_tables is True
    assert spec.tables == ("allocation",)


def test_a_relative_root_resolves_against_the_spec_not_the_caller(tmp_path: Path) -> None:
    """The same spec must mean the same thing whichever directory it was run from.

    Resolving against the process's working directory is the bug that only appears the first time
    somebody runs the spec from somewhere else, and then looks like data loss.
    """
    spec = StoreSpec.of({"root": "artifacts"}, base=tmp_path / "specs")

    assert spec.root == tmp_path / "specs" / "artifacts"


def test_an_absolute_root_is_taken_as_given(tmp_path: Path) -> None:
    spec = StoreSpec.of({"root": str(tmp_path / "elsewhere")}, base=tmp_path / "specs")

    assert spec.root == tmp_path / "elsewhere"


def test_an_undeclared_root_falls_back_to_the_workspace_directory(tmp_path: Path) -> None:
    """`store.root` is a lever, and a lever nobody pulls must leave things where they were."""
    spec = StoreSpec.of({"tables": ["allocation"]}, base=tmp_path)

    assert spec.resolve(tmp_path, ".vqapr") == tmp_path / ".vqapr"


def test_a_declared_root_moves_the_heavy_artifacts_off_the_catalog(tmp_path: Path) -> None:
    """The reason the lever exists: ~500MB of run output does not belong beside a small catalog.

    They have different lifetimes -- one is version-controlled and backed up, the other is
    regenerable bulk -- and one hardcoded path forced them together.
    """
    spec = StoreSpec.of({"root": str(tmp_path / "bulk")}, base=tmp_path)

    resolved = spec.resolve(tmp_path, ".vqapr")
    assert resolved == tmp_path / "bulk"
    assert resolved != tmp_path / ".vqapr"


@pytest.mark.parametrize(
    ("declared", "match"),
    [
        ({"nope": 1}, "store may contain"),
        ({"tables": "allocation"}, "must be a list"),
        ({"tables": ["a", "a"]}, "must not repeat"),
        ({"root": 3}, "must be a path string"),
        ("not-a-mapping", "must be a mapping"),
    ],
)
def test_a_malformed_store_block_is_refused_rather_than_guessed(
    declared: object, match: str, tmp_path: Path
) -> None:
    """A single string in `tables` would otherwise iterate into one table per character."""
    with pytest.raises((TypeError, ValueError), match=match):
        StoreSpec.of(declared, base=tmp_path)
