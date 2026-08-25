"""Unit tests for the content-addressed object store (`vqapr._internal.objects`)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from vqapr._internal.objects import (
    has_object,
    object_path,
    read_object,
    stage_many,
    stage_object,
)


def _objects_dir(root: Path) -> Path:
    return root / ".vqapr" / "objects" / "sha256"


def test_stage_object_returns_correct_digest_and_lands_at_expected_path(tmp_path: Path) -> None:
    payload = b"hello content-addressed world"
    expected_digest = hashlib.sha256(payload).hexdigest()

    digest = stage_object(tmp_path, payload)

    assert digest == expected_digest
    installed = object_path(tmp_path, digest)
    assert installed == _objects_dir(tmp_path) / digest
    assert installed.is_file()
    assert installed.read_bytes() == payload


def test_staging_same_payload_twice_is_idempotent_and_does_not_rewrite(tmp_path: Path) -> None:
    payload = b"idempotent payload"

    first_digest = stage_object(tmp_path, payload)
    installed = object_path(tmp_path, first_digest)
    mtime_before = installed.stat().st_mtime_ns

    second_digest = stage_object(tmp_path, payload)

    assert second_digest == first_digest
    mtime_after = installed.stat().st_mtime_ns
    assert mtime_after == mtime_before


def test_different_payloads_yield_different_digests_equal_payloads_yield_same_digest(
    tmp_path: Path,
) -> None:
    digest_a = stage_object(tmp_path, b"payload a")
    digest_b = stage_object(tmp_path, b"payload b")
    assert digest_a != digest_b

    # Two independent call sites staging byte-identical content converge on one digest.
    site_one = stage_object(tmp_path, b"shared payload")
    site_two = stage_object(tmp_path, b"shared payload")
    assert site_one == site_two


def test_no_temp_files_remain_after_successful_stage(tmp_path: Path) -> None:
    digests = stage_many(tmp_path, [b"one", b"two", b"three"])

    entries = sorted(p.name for p in _objects_dir(tmp_path).iterdir())
    assert entries == sorted(digests)


def test_read_object_round_trips_exactly(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 37
    digest = stage_object(tmp_path, payload)

    assert read_object(tmp_path, digest) == payload


def test_corrupted_object_raises_on_read_and_on_restage(tmp_path: Path) -> None:
    payload = b"trustworthy bytes"
    digest = stage_object(tmp_path, payload)
    installed = object_path(tmp_path, digest)

    installed.write_bytes(b"tampered bytes of a different length entirely")

    with pytest.raises(ValueError):
        read_object(tmp_path, digest)

    # stage_object must never silently repair/overwrite a corrupted object; it raises instead.
    with pytest.raises(ValueError):
        stage_object(tmp_path, payload)


@pytest.mark.parametrize(
    "bad_digest",
    [
        "short",
        "0" * 63,
        "0" * 65,
        "A" * 64,
        "g" * 64,
        "0123456789abcdef" * 4 + "z",
    ],
)
def test_invalid_digest_raises_value_error_everywhere(tmp_path: Path, bad_digest: str) -> None:
    with pytest.raises(ValueError):
        object_path(tmp_path, bad_digest)
    with pytest.raises(ValueError):
        read_object(tmp_path, bad_digest)
    with pytest.raises(ValueError):
        has_object(tmp_path, bad_digest)


_CHILD_SCRIPT = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    import vqapr._internal.objects as objects

    root = Path(sys.argv[1])
    payload_path = Path(sys.argv[2])
    payload = payload_path.read_bytes()

    # Simulate a crash between the fsync'd, digest-verified temp write and the atomic
    # install: the temp file is fully on disk by the time os.replace would be called, but
    # the process dies before the rename happens, so no final digest path is ever created.
    def _die_before_replace(*_args, **_kwargs):
        os._exit(1)

    objects.os.replace = _die_before_replace
    objects.stage_object(root, payload)
    """
)


def test_crash_before_replace_leaves_no_partial_object_and_parent_can_recover(
    tmp_path: Path,
) -> None:
    root = tmp_path
    payload = os.urandom(4 * 1024 * 1024)  # a few MB
    expected_digest = hashlib.sha256(payload).hexdigest()

    payload_path = tmp_path / "payload.bin"
    payload_path.write_bytes(payload)

    script_path = tmp_path / "crash_child.py"
    script_path.write_text(_CHILD_SCRIPT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path), str(root), str(payload_path)],
        capture_output=True,
        timeout=60,
    )

    # os._exit(1) inside the patched os.replace is what actually terminates the child.
    assert result.returncode == 1

    assert has_object(root, expected_digest) is False
    assert not object_path(root, expected_digest).exists()

    # The parent process can still complete a clean, fully verified stage of the same bytes.
    digest = stage_object(root, payload)
    assert digest == expected_digest
    assert read_object(root, digest) == payload
