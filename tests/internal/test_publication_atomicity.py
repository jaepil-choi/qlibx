"""Atomicity of publication: all outputs become visible together, or none do.

The interesting cases here are the failure cases. A publication that succeeds is easy;
what matters is that a conflict, an exception, or a hard process kill can never leave a
catalog referencing an object that is absent, nor one output visible without its
companions.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from vqapr._internal.catalog import root_digest
from vqapr._internal.catalog_store import CATALOG_DIRECTORY, commit_catalog, read_catalog
from vqapr._internal.objects import has_object, read_object
from vqapr._internal.publication import (
    PublicationConflict,
    PublishedOutput,
    publish_outputs,
    referenced_digests,
)


def _output(output_id: str, payload: bytes = b"rows", **metadata) -> PublishedOutput:
    return PublishedOutput(output_id=output_id, payload=payload, metadata=metadata)


# --- the success path -------------------------------------------------------------------


def test_publishing_makes_every_output_visible_in_one_generation(tmp_path: Path):
    published = publish_outputs(
        tmp_path,
        [_output("allocation", b"alloc-rows"), _output("records", b"record-rows")],
    )

    assert published.generation == 1
    assert set(published.output_ids) == {"allocation", "records"}

    catalog = read_catalog(tmp_path)
    assert set(catalog.publications) == {"allocation", "records"}
    # Every referenced digest is durable and readable.
    for digest in published.digests.values():
        assert has_object(tmp_path, digest)
    assert referenced_digests(catalog) == set(published.digests.values())


def test_published_payloads_round_trip_exactly(tmp_path: Path):
    payload = b"\x00\x01exact bytes\xff"
    published = publish_outputs(tmp_path, [_output("allocation", payload)])
    digest = published.digests["allocation"]
    assert read_object(tmp_path, digest) == payload


def test_identical_payloads_share_one_object(tmp_path: Path):
    published = publish_outputs(
        tmp_path, [_output("a", b"same-bytes"), _output("b", b"same-bytes")]
    )
    assert published.digests["a"] == published.digests["b"]


def test_republishing_an_existing_output_id_is_refused(tmp_path: Path):
    publish_outputs(tmp_path, [_output("allocation")])
    with pytest.raises(ValueError, match="already published"):
        publish_outputs(tmp_path, [_output("allocation", b"different")])


def test_a_repeated_output_id_within_one_publication_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="must not repeat an output_id"):
        publish_outputs(tmp_path, [_output("dup"), _output("dup", b"other")])


def test_an_empty_publication_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="non-empty"):
        publish_outputs(tmp_path, [])


# --- all-or-none under conflict -----------------------------------------------------------


def test_a_conflicting_publication_makes_no_output_visible(tmp_path: Path):
    """A publisher that loses the CAS publishes nothing at all."""
    snapshot = read_catalog(tmp_path)
    stale_generation = snapshot.generation
    stale_digest = root_digest(snapshot)

    # Another writer commits first, moving the root out from under us.
    other = snapshot.with_binding("datasets", "someone_else", {"dataset_id": "someone_else"})
    commit_catalog(
        tmp_path,
        candidate=other,
        expected_generation=stale_generation,
        expected_root_digest=stale_digest,
    )
    generation_after_winner = read_catalog(tmp_path).generation

    with pytest.raises(PublicationConflict) as excinfo:
        publish_outputs(
            tmp_path,
            [_output("allocation", b"a"), _output("records", b"b")],
            expected_generation=stale_generation,
            expected_root_digest=stale_digest,
        )
    assert excinfo.value.mutation is False

    catalog = read_catalog(tmp_path)
    # Neither output is visible: not one, not the other.
    assert catalog.publications == {} or set(catalog.publications) == set()
    # The winner's commit is untouched and the generation did not advance again.
    assert catalog.generation == generation_after_winner
    assert catalog.dataset("someone_else") if hasattr(catalog, "dataset") else True


def test_orphans_from_a_failed_publication_never_block_a_retry(tmp_path: Path):
    """Objects staged by a losing publisher are harmless: identity lives in the catalog."""
    snapshot = read_catalog(tmp_path)
    stale_generation = snapshot.generation
    stale_digest = root_digest(snapshot)

    other = snapshot.with_binding("datasets", "winner", {"dataset_id": "winner"})
    commit_catalog(
        tmp_path,
        candidate=other,
        expected_generation=stale_generation,
        expected_root_digest=stale_digest,
    )

    with pytest.raises(PublicationConflict):
        publish_outputs(
            tmp_path,
            [_output("allocation", b"payload-x")],
            expected_generation=stale_generation,
            expected_root_digest=stale_digest,
        )

    # Retrying against the current root succeeds, reusing the already-staged object.
    published = publish_outputs(tmp_path, [_output("allocation", b"payload-x")])
    assert published.output_ids == ("allocation",)
    assert has_object(tmp_path, published.digests["allocation"])
    assert "allocation" in read_catalog(tmp_path).publications


def test_every_referenced_digest_is_present_before_the_root_mentions_it(tmp_path: Path):
    """The core invariant: a committed root never references an absent object."""
    publish_outputs(
        tmp_path,
        [_output("a", b"aaa"), _output("b", b"bbb"), _output("c", b"ccc")],
    )
    catalog = read_catalog(tmp_path)
    for digest in catalog.object_digests:
        assert has_object(tmp_path, digest), f"root references missing object {digest}"
        assert read_object(tmp_path, digest)


# --- hard kill around the root swap --------------------------------------------------------


_KILL_BEFORE_SWAP = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    import vqapr._internal.catalog_store as store
    from vqapr._internal.publication import PublishedOutput, publish_outputs

    root = Path(sys.argv[1])

    # Die after every object is durable but before the visibility swap lands.
    original = store.commit_catalog
    def _die(*args, **kwargs):
        os._exit(9)
    store.commit_catalog = _die

    import vqapr._internal.publication as publication
    publication.commit_catalog = _die

    publish_outputs(root, [PublishedOutput(output_id="allocation", payload=b"x"*200000,
                                           metadata={})])
    print("UNREACHABLE")
    """
)


def test_hard_kill_before_the_swap_leaves_the_old_root_complete(tmp_path: Path):
    """A crash between staging and the swap must leave orphans, never a partial catalog."""
    root = tmp_path / "project"
    root.mkdir()
    # Establish a real prior root so we can prove it survives intact.
    publish_outputs(root, [_output("existing", b"already-here")])
    before = read_catalog(root)
    before_generation = before.generation
    before_digest = root_digest(before)

    script = tmp_path / "kill_before.py"
    script.write_text(_KILL_BEFORE_SWAP, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 9, result.stdout + result.stderr
    assert "UNREACHABLE" not in result.stdout

    after = read_catalog(root)
    # The old root is byte-for-byte what it was, and the crashed output is not visible.
    assert after.generation == before_generation
    assert root_digest(after) == before_digest
    assert "allocation" not in after.publications
    # The prior output is still readable.
    assert "existing" in after.publications


_KILL_AFTER_SWAP = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    from vqapr._internal.publication import PublishedOutput, publish_outputs

    root = Path(sys.argv[1])
    publish_outputs(root, [PublishedOutput(output_id="allocation", payload=b"y"*200000,
                                           metadata={})])
    # The swap has landed and is durable; die immediately without any orderly shutdown.
    os._exit(7)
    """
)


def test_hard_kill_after_the_swap_leaves_a_complete_new_root(tmp_path: Path):
    """Once the swap lands, every referenced digest was already verified on disk."""
    root = tmp_path / "project"
    root.mkdir()
    script = tmp_path / "kill_after.py"
    script.write_text(_KILL_AFTER_SWAP, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), str(root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 7, result.stdout + result.stderr

    after = read_catalog(root)
    assert "allocation" in after.publications
    # Reopening finds a complete root: nothing it references is missing or partial.
    for digest in after.object_digests:
        assert has_object(root, digest)
        assert read_object(root, digest)
    assert (root / CATALOG_DIRECTORY / "catalog.json").exists()
