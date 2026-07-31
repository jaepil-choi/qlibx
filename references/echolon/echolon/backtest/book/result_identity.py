"""Canonical, independently verifiable identity for a complete book result."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping

from .models import BookResult


FULL_RESULT_MANIFEST_SCHEMA = "book-full-result-manifest/v1"


def full_result_manifest_payload(
    result: BookResult | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the canonical payload, excluding only its own digest field."""
    validated = (
        result
        if isinstance(result, BookResult)
        else BookResult.model_validate(dict(result))
    )
    result_payload = validated.model_dump(mode="json")
    result_payload["summary"].pop("full_result_manifest_sha256")
    return {"schema": FULL_RESULT_MANIFEST_SCHEMA, "result": result_payload}


def full_result_manifest_sha256(
    result: BookResult | Mapping[str, Any],
) -> str:
    """Recompute the non-circular SHA-256 identity of a returned book result."""
    encoded = json.dumps(
        full_result_manifest_payload(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_full_result_manifest_sha256(
    result: BookResult | Mapping[str, Any],
) -> bool:
    """Return whether the embedded full-result digest matches recomputation."""
    validated = (
        result
        if isinstance(result, BookResult)
        else BookResult.model_validate(dict(result))
    )
    expected = validated.summary.full_result_manifest_sha256
    actual = full_result_manifest_sha256(validated)
    return hmac.compare_digest(expected, actual)
