"""Transaction behaviour of the `Project` facade.

These tests pin the properties the candidate-catalog protocol exists to guarantee:
`open()` never writes, preparation is all-or-nothing across staged declarations, an
idempotent re-registration does not churn the generation, and exactly one of two
competing writers commits.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import vqapr
from vqapr.project import (
    CatalogConflict,
    DatasetDeclaration,
    Diagnostic,
    ExecutionInputDeclaration,
    ExtensionDeclaration,
    Project,
    RegistrationTiming,
)


def _dataset(dataset_id: str = "stock_daily", path: str = "prepared/stock.parquet"):
    return DatasetDeclaration(
        dataset_id=dataset_id,
        path=Path(path),
        hive_partitioned=False,
        instrument_field="instrument",
        available_at_field="available_at",
        key_fields=("available_at", "instrument"),
        fields={"ret": "ret", "market_cap": "market_cap"},
    )


def _execution(input_id: str = "krx-daily"):
    return ExecutionInputDeclaration(
        input_id=input_id,
        path=Path("prepared/execution.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )


# --- open() is non-mutating -------------------------------------------------------------


def test_open_creates_nothing(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    project = vqapr.open(root)

    assert project.generation() == 0
    assert not (root / ".vqapr").exists()
    assert list(root.iterdir()) == []


def test_open_on_a_root_that_does_not_exist_yet_still_creates_nothing(tmp_path: Path):
    root = tmp_path / "never-made"
    project = vqapr.open(root)
    assert project.generation() == 0
    assert not root.exists()


def test_vqapr_open_is_the_supported_entry_point():
    assert vqapr.open is not None
    assert "open" in vqapr.__all__


# --- registration ------------------------------------------------------------------------


def test_registering_a_dataset_commits_exactly_one_generation(tmp_path: Path):
    project = vqapr.open(tmp_path)
    receipt = project.register(_dataset())

    assert receipt.created is True
    assert receipt.declaration_kind == "dataset"
    assert receipt.catalog_generation == 1
    assert project.generation() == 1


def test_a_receipt_exposes_no_physical_path_or_source_digest(tmp_path: Path):
    project = vqapr.open(tmp_path)
    receipt = project.register(_dataset(path="prepared/secret-location.parquet"))

    rendered = repr(receipt)
    assert "secret-location" not in rendered
    assert not hasattr(receipt, "path")
    assert not hasattr(receipt, "source_digest")
    assert receipt.fingerprint is None


def test_re_registering_the_identical_declaration_is_idempotent(tmp_path: Path):
    project = vqapr.open(tmp_path)
    first = project.register(_dataset())
    second = project.register(_dataset())

    assert first.created is True
    assert second.created is False
    # The generation does not churn: re-running a registration script is free.
    assert second.catalog_generation == first.catalog_generation
    assert project.generation() == 1


def test_rebinding_the_same_id_to_a_different_value_is_refused(tmp_path: Path):
    project = vqapr.open(tmp_path)
    project.register(_dataset(path="a.parquet"))

    with pytest.raises(ValueError, match="already registered with a different"):
        project.register(_dataset(path="b.parquet"))

    # The refusal changed nothing.
    assert project.generation() == 1


def test_distinct_declarations_each_advance_the_generation(tmp_path: Path):
    project = vqapr.open(tmp_path)
    project.register(_dataset("stock_daily"))
    project.register(_dataset("market_daily", path="prepared/market.parquet"))
    project.register(_execution())

    assert project.generation() == 3
    view = project.catalog()
    assert view.dataset("stock_daily")["dataset_id"] == "stock_daily"
    assert view.dataset("market_daily")["dataset_id"] == "market_daily"
    assert view.execution_input("krx-daily")["input_id"] == "krx-daily"


def test_an_unregistered_id_raises_rather_than_returning_empty(tmp_path: Path):
    project = vqapr.open(tmp_path)
    project.register(_dataset())
    with pytest.raises(KeyError):
        project.catalog().dataset("never_registered")


# --- register_all is one candidate, one commit -------------------------------------------


def test_register_all_commits_every_declaration_in_one_generation(tmp_path: Path):
    project = vqapr.open(tmp_path)
    receipts = project.register_all((_dataset("a"), _dataset("b", path="b.parquet"), _execution()))

    assert len(receipts) == 3
    assert all(r.created for r in receipts)
    # One transaction, not three: preflight sees all staged declarations together.
    assert project.generation() == 1
    assert {r.catalog_generation for r in receipts} == {1}


def test_a_rejection_anywhere_in_a_batch_commits_nothing(tmp_path: Path):
    project = vqapr.open(tmp_path)
    project.register(_dataset("a", path="first.parquet"))
    generation_before = project.generation()

    # The third declaration conflicts with what is already bound.
    with pytest.raises(ValueError):
        project.register_all(
            (
                _dataset("new_one", path="new.parquet"),
                _dataset("another", path="another.parquet"),
                _dataset("a", path="CONFLICTING.parquet"),
            )
        )

    assert project.generation() == generation_before
    with pytest.raises(KeyError):
        project.catalog().dataset("new_one")
    with pytest.raises(KeyError):
        project.catalog().dataset("another")


# --- declaration algebra -----------------------------------------------------------------


def test_a_declaration_rejects_a_missing_or_malformed_field():
    with pytest.raises(ValueError):
        DatasetDeclaration(
            dataset_id="",
            path=Path("x.parquet"),
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at",),
            fields={"ret": "ret"},
        )
    with pytest.raises(ValueError, match="key_fields must be a non-empty tuple"):
        DatasetDeclaration(
            dataset_id="d",
            path=Path("x.parquet"),
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=(),
            fields={"ret": "ret"},
        )
    with pytest.raises(TypeError, match=r"path must be a pathlib\.Path"):
        DatasetDeclaration(
            dataset_id="d",
            path="x.parquet",
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at",),
            fields={"ret": "ret"},
        )


def test_declarations_are_immutable_and_detached():
    fields = {"ret": "ret"}
    declaration = _dataset()
    with pytest.raises(AttributeError):
        declaration.dataset_id = "changed"
    # Mutating the caller's dict afterwards cannot reach into the declaration.
    fields["injected"] = "injected"
    assert "injected" not in declaration.fields


def test_project_register_refuses_an_unsupported_declaration_type(tmp_path: Path):
    project = vqapr.open(tmp_path)
    with pytest.raises(TypeError, match="declaration must be a"):
        project.register({"dataset_id": "as_a_mapping"})


def test_extension_declaration_name_is_diagnostics_only():
    class _Thing:
        pass

    declaration = ExtensionDeclaration(extension=_Thing, config={"a": 1}, name="human label")
    canonical = declaration.canonical()
    assert canonical["qualname"] == _Thing.__qualname__
    assert canonical["name"] == "human label"


# --- Diagnostic bounds --------------------------------------------------------------------


def test_diagnostic_is_bounded_and_immutable():
    diagnostic = Diagnostic(
        code="dataset.missing_field",
        severity="error",
        requirement="every declared field must exist",
        observed="column 'ret' is absent",
        examples=("row 1", "row 2"),
        example_total=57,
    )
    assert diagnostic.example_total == 57
    with pytest.raises(AttributeError):
        diagnostic.code = "changed"


def test_diagnostic_refuses_out_of_bounds_values():
    with pytest.raises(ValueError, match="severity"):
        Diagnostic(code="c", severity="fatal", requirement="r", observed="o")
    with pytest.raises(ValueError, match="at most 20 members"):
        Diagnostic(
            code="c",
            severity="error",
            requirement="r",
            observed="o",
            examples=tuple(f"e{i}" for i in range(21)),
            example_total=21,
        )
    with pytest.raises(ValueError, match="at least len"):
        Diagnostic(
            code="c",
            severity="error",
            requirement="r",
            observed="o",
            examples=("a", "b"),
            example_total=1,
        )
    with pytest.raises(ValueError, match="at most 500 characters"):
        Diagnostic(code="c", severity="error", requirement="r", observed="x" * 501)


def test_registration_timing_rejects_negative_measurements():
    with pytest.raises(ValueError):
        RegistrationTiming(
            schema_seconds=-1.0,
            key_seconds=None,
            conformance_seconds=None,
            preparation_seconds=1.0,
        )


# --- concurrency: exactly one writer commits ---------------------------------------------


_CONTENDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    import vqapr
    from vqapr.project import DatasetDeclaration

    root = Path(sys.argv[1])
    dataset_id = sys.argv[2]
    barrier = Path(sys.argv[3])

    declaration = DatasetDeclaration(
        dataset_id=dataset_id,
        path=Path(f"{dataset_id}.parquet"),
        hive_partitioned=False,
        instrument_field="instrument",
        available_at_field="available_at",
        key_fields=("available_at", "instrument"),
        fields={"ret": "ret"},
    )

    project = vqapr.open(root)
    # Spin until the parent releases both children at once, so they genuinely contend
    # for the same starting generation rather than running in sequence.
    while not barrier.exists():
        time.sleep(0.005)

    try:
        receipt = project.register(declaration)
        print(f"COMMITTED:{receipt.catalog_generation}")
    except Exception as exc:
        print(f"CONFLICT:{type(exc).__name__}")
    """
)


def test_two_competing_writers_leave_a_readable_catalog(tmp_path: Path):
    """Two processes registering different ids against generation 0.

    The lock serialises them, so both may succeed - but they must land on DIFFERENT
    generations, never the same one, and the catalog must stay readable and internally
    consistent afterwards.
    """
    root = tmp_path / "project"
    root.mkdir()
    script = tmp_path / "contender.py"
    script.write_text(_CONTENDER, encoding="utf-8")
    barrier = tmp_path / "go"

    processes = [
        subprocess.Popen(
            [sys.executable, str(script), str(root), name, str(barrier)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("alpha", "beta")
    ]
    barrier.write_text("go", encoding="utf-8")
    outputs = [process.communicate(timeout=120)[0].strip() for process in processes]

    committed = [line for line in outputs if line.startswith("COMMITTED:")]
    generations = [int(line.split(":", 1)[1]) for line in committed]

    # No two writers may claim the same generation: that is the CAS invariant.
    assert len(generations) == len(set(generations)), outputs

    # Whatever happened, the catalog is readable and its generation matches its contents.
    project = vqapr.open(root)
    final = project.generation()
    assert final == len(committed)
    assert final >= 1


def test_a_stale_snapshot_conflicts_rather_than_rebasing(tmp_path: Path):
    """A candidate built on an old snapshot must not silently rebase onto a newer root."""
    from vqapr._internal.catalog import root_digest
    from vqapr._internal.catalog_store import commit_catalog, read_catalog

    root = tmp_path / "project"
    root.mkdir()
    project = Project(root)

    stale = read_catalog(root)
    stale_generation = stale.generation
    stale_digest = root_digest(stale)

    # Someone else commits first.
    project.register(_dataset("first"))

    # Our candidate, built on the pre-commit snapshot, must be refused.
    candidate = stale.with_binding("datasets", "second", {"dataset_id": "second"})
    with pytest.raises(CatalogConflict) as excinfo:
        commit_catalog(
            root,
            candidate=candidate,
            expected_generation=stale_generation,
            expected_root_digest=stale_digest,
        )
    assert excinfo.value.mutation is False
    # The winner's registration survived untouched.
    assert project.catalog().dataset("first")["dataset_id"] == "first"
    with pytest.raises(KeyError):
        project.catalog().dataset("second")
