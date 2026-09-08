"""A declaration document registers as one transaction, or not at all.

Campaign Step 2; the testbed's A3. `_apply` used to call a `Workspace.register_*` per item, each
taking the lock and writing the whole document, so a document refused at its k-th item left items
1..k-1 registered -- and, registrations being immutable, the corrected document then conflicted at
item 1. The only recovery the testbed found was deleting `.vqapr/`.

Three properties, asserted directly:

- a document refused at item k leaves `.vqapr/` **byte-identical** to before;
- a valid document is **one** write, however many items it declares;
- a document refused before anything could be staged, in a directory with no workspace, creates
  nothing -- not even the directory.

The later item is a run (record `148`): a run takes its sessions from a dataset and names its
strategies, so it is the declaration that can follow a dataset in the same document and the one
that can be refused for naming something absent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vqapr import workspace as workspace_module
from vqapr.declarations import apply
from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.inputs import InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace


def _fingerprint(root: Path) -> dict[str, str]:
    workspace = root / WORKSPACE_DIRECTORY
    if not workspace.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def _dataset(source_id: str, parquet: Path) -> dict[str, object]:
    return {
        "source_id": source_id,
        "path": str(parquet),
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ["available_at", "instrument"],
        "grain": "instrument_instant",
        "fields": {"close": "close"},
        "field_types": {"close": "DOUBLE"},
    }


def _run(sessions_from: str, *, strategy: str = "alpha", at: str = "04:00") -> dict:
    return {
        "instruments": ["A"],
        "start": None,
        "end": None,
        "timezone": "Asia/Seoul",
        "at": at,
        "sessions_from": sessions_from,
        "exchange": None,
        "execution_input": None,
        "initial_account": {"cash": "1000", "mode": "long_only", "positions": {}},
        "strategies": {strategy: None},
    }


def _register_a_strategy(root: Path, name: str = "alpha") -> None:
    """A strategy the run can name, registered ahead of the document under test.

    Registered directly rather than through the document: a `components:` entry loads the file
    to fingerprint it, and what these tests measure is the write, not component loading.
    """
    with Workspace.transaction(root) as t:
        t.register_component(
            ComponentRef.of(
                name,
                ComponentKind.STRATEGY_MODEL,
                root / f"{name}.py",
                "Strategy",
                fingerprint="a" * 64,
            )
        )


def test_a_document_refused_at_its_kth_item_leaves_the_workspace_byte_identical(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The acceptance criterion, verbatim from the campaign doc."""
    first = {"datasets": {"price_a": _dataset("src-a", model_price_parquet)}}
    apply(first, tmp_path, base=tmp_path)
    before = _fingerprint(tmp_path)
    assert before, "the first document must have created a workspace to protect"

    # Item 1 (a second dataset) is valid; item 2 (a run) names a strategy nobody registered.
    refused = {
        "datasets": {"price_b": _dataset("src-b", model_price_parquet)},
        "runs": {"daily": _run("price_b", strategy="nonexistent")},
    }
    with pytest.raises(VqaprError):
        apply(refused, tmp_path, base=tmp_path)

    assert _fingerprint(tmp_path) == before
    registered = {str(item.dataset_id) for item in Workspace.open(tmp_path).datasets}
    assert registered == {"price_a"}, "the valid item before the refusal must not have landed"


def test_a_valid_document_is_one_write(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two datasets, and a run taking its sessions from a dataset declared in the same document."""
    _register_a_strategy(tmp_path)
    writes: list[Path] = []
    original = workspace_module.atomic.write_atomically

    def counting(target: Path, payload: bytes | str, **kwargs: object) -> None:
        writes.append(Path(target))
        original(target, payload, **kwargs)

    monkeypatch.setattr(workspace_module.atomic, "write_atomically", counting)

    document = {
        "datasets": {
            "price_a": _dataset("src-a", model_price_parquet),
            "price_b": _dataset("src-b", model_price_parquet),
        },
        "runs": {"daily": _run("price_b")},
    }
    registered = apply(document, tmp_path, base=tmp_path)

    assert registered["datasets"] == ["price_a", "price_b"]
    assert registered["runs"] == ["daily"]
    assert len(writes) == 1, [str(path) for path in writes]
    reopened = Workspace.open(tmp_path)
    assert {str(item.dataset_id) for item in reopened.datasets} == {"price_a", "price_b"}
    assert reopened.run_definition("daily").sessions_from == "price_b"


def test_an_idempotent_document_writes_nothing(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registering the same document twice is the single-item idempotence, per document."""
    _register_a_strategy(tmp_path)
    document = {
        "datasets": {"price_a": _dataset("src-a", model_price_parquet)},
        "runs": {"daily": _run("price_a")},
    }
    apply(document, tmp_path, base=tmp_path)
    before = _fingerprint(tmp_path)
    writes: list[Path] = []
    original = workspace_module.atomic.write_atomically

    def counting(target: Path, payload: bytes | str, **kwargs: object) -> None:
        writes.append(Path(target))
        original(target, payload, **kwargs)

    monkeypatch.setattr(workspace_module.atomic, "write_atomically", counting)

    apply(document, tmp_path, base=tmp_path)

    assert writes == []
    assert _fingerprint(tmp_path) == before


def test_a_document_refused_before_staging_creates_no_workspace(tmp_path: Path) -> None:
    """In an empty directory a refused document leaves the directory empty."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    with pytest.raises((VqaprError, InputError)):
        apply({"datasets": {"broken": {"source_id": "only-this-key"}}}, fresh, base=fresh)

    assert not (fresh / WORKSPACE_DIRECTORY).exists()
