"""Unit tests for `vqapr._internal.catalog` and `vqapr._internal.catalog_store`."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from vqapr._internal.catalog import (
    CATALOG_SCHEMA,
    Catalog,
    CatalogView,
    canonical_bytes,
    root_digest,
)
from vqapr._internal.catalog_store import (
    CATALOG_DIRECTORY,
    CatalogConflict,
    commit_catalog,
    read_catalog,
    sweep_orphans,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


# --- Catalog value type ------------------------------------------------------------------


def test_empty_catalog_is_generation_zero_with_no_bindings():
    catalog = Catalog.empty()
    assert catalog.schema == CATALOG_SCHEMA
    assert catalog.generation == 0
    assert dict(catalog.datasets) == {}
    assert catalog.object_digests == ()


def test_generation_rejects_bool_and_negative():
    with pytest.raises(TypeError):
        Catalog(
            schema=CATALOG_SCHEMA,
            generation=True,
            datasets={},
            execution_inputs={},
            extensions={},
            publications={},
        )
    with pytest.raises(ValueError):
        Catalog(
            schema=CATALOG_SCHEMA,
            generation=-1,
            datasets={},
            execution_inputs={},
            extensions={},
            publications={},
        )


def test_binding_key_rejects_empty_and_whitespace():
    catalog = Catalog.empty()
    with pytest.raises(ValueError):
        catalog.with_binding("datasets", "", {"a": 1})
    with pytest.raises(ValueError):
        catalog.with_binding("datasets", "has space", {"a": 1})


def test_object_digest_validation():
    with pytest.raises(ValueError):
        Catalog.empty().with_objects(["not-a-digest"])
    with pytest.raises(ValueError):
        Catalog.empty().with_objects(["A" * 64])  # uppercase rejected


def test_with_objects_dedupes_and_sorts():
    catalog = Catalog.empty().with_objects([DIGEST_B, DIGEST_A]).with_objects([DIGEST_A, DIGEST_C])
    assert catalog.object_digests == (DIGEST_A, DIGEST_B, DIGEST_C)


def test_with_binding_never_mutates_receiver():
    original = Catalog.empty()
    updated = original.with_binding("datasets", "price_daily", {"field": "close"})
    assert original.generation == 0
    assert dict(original.datasets) == {}
    assert updated is not original
    assert dict(updated.datasets) == {"price_daily": {"field": "close"}}


def test_with_binding_idempotent_for_identical_value():
    catalog = Catalog.empty().with_binding("datasets", "price_daily", {"field": "close"})
    again = catalog.with_binding("datasets", "price_daily", {"field": "close"})
    assert again == catalog


def test_with_binding_conflict_raises_value_error():
    catalog = Catalog.empty().with_binding("datasets", "price_daily", {"field": "close"})
    with pytest.raises(ValueError):
        catalog.with_binding("datasets", "price_daily", {"field": "open"})


def test_binding_mappings_are_deeply_read_only():
    catalog = Catalog.empty().with_binding("datasets", "price_daily", {"field": "close"})
    with pytest.raises(TypeError):
        catalog.datasets["price_daily"]["field"] = "open"  # type: ignore[index]
    with pytest.raises(TypeError):
        catalog.datasets["new_key"] = {}  # type: ignore[index]


# --- canonical_bytes / root_digest --------------------------------------------------------


def test_canonical_bytes_is_insertion_order_independent():
    a = (
        Catalog.empty()
        .with_binding("datasets", "b_id", {"x": 1})
        .with_binding("datasets", "a_id", {"y": 2})
        .with_objects([DIGEST_B, DIGEST_A])
    )
    b = (
        Catalog.empty()
        .with_binding("datasets", "a_id", {"y": 2})
        .with_binding("datasets", "b_id", {"x": 1})
        .with_objects([DIGEST_A, DIGEST_B])
    )
    assert canonical_bytes(a) == canonical_bytes(b)
    assert root_digest(a) == root_digest(b)


def test_canonical_bytes_has_no_insignificant_whitespace():
    catalog = Catalog.empty().with_binding("datasets", "price_daily", {"field": "close"})
    encoded = canonical_bytes(catalog)
    assert b" " not in encoded
    assert b"\n" not in encoded


# --- CatalogView --------------------------------------------------------------------------


def test_catalog_view_lookup_and_missing_key_error():
    catalog = Catalog.empty().with_binding("datasets", "price_daily", {"field": "close"})
    view = CatalogView(catalog)
    assert dict(view.dataset("price_daily")) == {"field": "close"}
    with pytest.raises(KeyError):
        view.dataset("missing_id")
    assert view.generation == 0


def test_catalog_view_has_no_mutating_method():
    view = CatalogView(Catalog.empty())
    public_methods = {name for name in dir(view) if not name.startswith("_")}
    forbidden = {"with_binding", "with_objects", "commit", "write", "set", "update", "delete"}
    assert public_methods.isdisjoint(forbidden)


def test_catalog_view_requires_catalog_instance():
    with pytest.raises(TypeError):
        CatalogView({"not": "a catalog"})  # type: ignore[arg-type]


# --- catalog_store: read_catalog is non-mutating -------------------------------------------


def test_read_catalog_on_fresh_path_returns_empty_and_creates_nothing(tmp_path: Path):
    catalog = read_catalog(tmp_path)
    assert catalog.generation == 0
    assert catalog == Catalog.empty()
    assert not (tmp_path / CATALOG_DIRECTORY).exists()


# --- catalog_store: commit_catalog CAS -----------------------------------------------------


def _snapshot(root: Path):
    current = read_catalog(root)
    return current, current.generation, root_digest(current)


def test_successful_commit_increments_generation_and_round_trips(tmp_path: Path):
    current, generation, digest = _snapshot(tmp_path)
    candidate = current.with_binding("datasets", "price_daily", {"field": "close"})
    committed = commit_catalog(
        tmp_path, candidate=candidate, expected_generation=generation, expected_root_digest=digest
    )
    assert committed.generation == generation + 1
    reread = read_catalog(tmp_path)
    assert reread.generation == committed.generation
    assert root_digest(reread) == root_digest(committed)
    assert dict(reread.datasets) == {"price_daily": {"field": "close"}}


def test_stale_generation_raises_conflict_and_leaves_root_untouched(tmp_path: Path):
    current, generation, digest = _snapshot(tmp_path)
    first = current.with_binding("datasets", "a", {"v": 1})
    commit_catalog(
        tmp_path, candidate=first, expected_generation=generation, expected_root_digest=digest
    )
    before = (tmp_path / CATALOG_DIRECTORY / "catalog.json").read_bytes()

    stale_candidate = current.with_binding("datasets", "b", {"v": 2})
    with pytest.raises(CatalogConflict) as excinfo:
        commit_catalog(
            tmp_path,
            candidate=stale_candidate,
            expected_generation=generation,
            expected_root_digest=digest,
        )
    assert excinfo.value.mutation is False
    assert excinfo.value.expected_generation == generation
    assert excinfo.value.observed_generation == generation + 1

    after = (tmp_path / CATALOG_DIRECTORY / "catalog.json").read_bytes()
    assert before == after


def test_stale_root_digest_at_correct_generation_raises_conflict(tmp_path: Path):
    current, generation, digest = _snapshot(tmp_path)
    wrong_digest = "0" * 64
    assert wrong_digest != digest
    with pytest.raises(CatalogConflict) as excinfo:
        commit_catalog(
            tmp_path,
            candidate=current.with_binding("datasets", "a", {"v": 1}),
            expected_generation=generation,
            expected_root_digest=wrong_digest,
        )
    assert excinfo.value.mutation is False
    assert excinfo.value.expected_generation == generation
    assert excinfo.value.observed_generation == generation


def test_two_sequential_commits_from_same_stale_snapshot_first_wins(tmp_path: Path):
    current, generation, digest = _snapshot(tmp_path)
    candidate_1 = current.with_binding("datasets", "first", {"v": 1})
    candidate_2 = current.with_binding("datasets", "second", {"v": 2})

    committed_1 = commit_catalog(
        tmp_path, candidate=candidate_1, expected_generation=generation, expected_root_digest=digest
    )
    assert committed_1.generation == generation + 1

    with pytest.raises(CatalogConflict):
        commit_catalog(
            tmp_path,
            candidate=candidate_2,
            expected_generation=generation,
            expected_root_digest=digest,
        )


# --- catalog_store: sweep_orphans -----------------------------------------------------------


def _make_object(root: Path, digest: str, *, age_seconds: float) -> Path:
    objects_dir = root / CATALOG_DIRECTORY / "objects" / "sha256"
    objects_dir.mkdir(parents=True, exist_ok=True)
    path = objects_dir / digest
    path.write_bytes(b"payload")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_sweep_orphans_removes_old_unreferenced_keeps_referenced_and_young(tmp_path: Path):
    old_unreferenced = _make_object(tmp_path, DIGEST_A, age_seconds=100_000)
    old_referenced = _make_object(tmp_path, DIGEST_B, age_seconds=100_000)
    young_unreferenced = _make_object(tmp_path, DIGEST_C, age_seconds=10)

    removed = sweep_orphans(tmp_path, referenced={DIGEST_B}, grace_seconds=86400.0)

    assert removed == (DIGEST_A,)
    assert not old_unreferenced.exists()
    assert old_referenced.exists()
    assert young_unreferenced.exists()


def test_sweep_orphans_on_missing_objects_dir_returns_empty(tmp_path: Path):
    assert sweep_orphans(tmp_path, referenced=set()) == ()


# --- A failed first registration must leave the root untouched --------------------------


def test_failed_first_commit_leaves_no_catalog_directory(tmp_path: Path):
    """`Project.open()` is safe to call before a first successful registration.

    Taking the writer lock has to create `.vqapr/`, so a conflict on the very first commit
    would otherwise strand an empty directory in a root the caller never wrote to.
    """
    root = tmp_path / "project"
    root.mkdir()
    empty = read_catalog(root)
    candidate = empty.with_binding("datasets", "stock_daily", {"path": "x.parquet"})

    with pytest.raises(CatalogConflict):
        commit_catalog(
            root,
            candidate=candidate,
            expected_generation=7,
            expected_root_digest=root_digest(empty),
        )

    assert not (root / CATALOG_DIRECTORY).exists()


def test_a_later_conflict_never_removes_a_committed_catalog(tmp_path: Path):
    """Only a directory this writer created is cleaned up; real state is never swept."""
    root = tmp_path / "project"
    root.mkdir()
    empty = read_catalog(root)
    candidate = empty.with_binding("datasets", "stock_daily", {"path": "x.parquet"})
    commit_catalog(
        root,
        candidate=candidate,
        expected_generation=0,
        expected_root_digest=root_digest(empty),
    )

    with pytest.raises(CatalogConflict):
        commit_catalog(
            root,
            candidate=candidate,
            expected_generation=0,
            expected_root_digest=root_digest(empty),
        )

    assert (root / CATALOG_DIRECTORY / "catalog.json").exists()
    assert read_catalog(root).generation == 1
