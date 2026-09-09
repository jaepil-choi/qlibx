"""A detached state candidate, and the exact bytes its reference is taken over.

This was `flow/model_state.py` until one-shape Step 6 folded it into `flow/run_state.py`, and it
comes back out here rather than there (record `195`). Nothing about it is execution: it normalizes a
memory, frames it with a payload into one envelope, and hashes that. No clock, no account, no IO.

It is here because three layers exchange it and none owns it. `flow/run_state.py` proves a
candidate's ref before publishing it, `flow/run/callback.py` takes the ref of what a callback
committed, and a `StrategyConfig` in `project/run.py` derives the ref of the memory a run starts
with -- a **declaration**, which is what made the old home a layering problem: the project layer
had to import the engine to name the seed state it declares.

`ModelStateRef` is `domain/identifiers.py`'s and `normalize_memory` is `domain/values.py`'s, so
this sits directly on top of the two things it is made of.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.values import ModelMemory, normalize_memory


@dataclass(frozen=True, slots=True)
class PreparedModelState:
    """A detached state candidate with no visibility until its root is published."""

    ref: ModelStateRef
    memory: ModelMemory
    payload: bytes


def prepare_model_state(memory: object, payload: bytes) -> PreparedModelState:
    """Detach one exact memory/payload envelope without making it visible."""
    normalized = normalize_memory(memory)
    memory_bytes = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope = (
        len(memory_bytes).to_bytes(8, "big")
        + memory_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return PreparedModelState(
        ref=ModelStateRef(hashlib.sha256(envelope).hexdigest()),
        memory=normalized,
        payload=bytes(payload),
    )
