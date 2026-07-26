from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from qlib_extended.hashing import deterministic_run_id, stable_hash
from qlib_extended.models import RunRecord
from qlib_extended.store import ParentLink, RunCatalog


def publish_alpha_node(
    store: RunCatalog,
    *,
    strategy_id: str,
    alpha: pd.DataFrame,
    definition: Mapping[str, object],
    artifacts: Mapping[str, pd.DataFrame] | None = None,
    parents: Sequence[ParentLink] = (),
) -> str:
    parent_definition = tuple(
        (parent.run_id, parent.role, parent.weight) for parent in parents
    )
    identity = {
        "strategy_id": strategy_id,
        "definition": dict(definition),
        "parents": parent_definition,
        "alpha_digest": frame_digest(alpha),
    }
    run_id = deterministic_run_id("alpha", identity)
    payload = {"alpha": alpha, **dict(artifacts or {})}
    store.publish(
        RunRecord(
            run_id=run_id,
            run_kind="alpha",
            strategy_id=strategy_id,
            status="complete",
            config_fingerprint=stable_hash(definition),
            dataset_fingerprint=frame_digest(alpha),
            strategy_fingerprint=stable_hash(
                {"implementation": "report_twin_v1", "definition": dict(definition)}
            ),
            metadata={
                "report_twin": True,
                "definition": dict(definition),
                "parent_count": len(parents),
            },
        ),
        payload,
        parents=parents,
    )
    return run_id


def publish_backtest_node(
    store: RunCatalog,
    *,
    strategy_id: str,
    alpha_run_id: str,
    artifacts: Mapping[str, pd.DataFrame],
    metadata: Mapping[str, object],
) -> str:
    result_hash = str(metadata["result_hash"])
    run_id = deterministic_run_id(
        "backtest",
        {
            "strategy_id": strategy_id,
            "alpha_run_id": alpha_run_id,
            "result_hash": result_hash,
        },
    )
    store.publish(
        RunRecord(
            run_id=run_id,
            run_kind="backtest",
            strategy_id=strategy_id,
            status="complete",
            config_fingerprint=stable_hash({"target_semantics": "target_weight"}),
            dataset_fingerprint=stable_hash(
                {"alpha_run_id": alpha_run_id, "result_hash": result_hash}
            ),
            strategy_fingerprint=stable_hash("report_twin_qlib_physical_v1"),
            metadata={"report_twin": True, **dict(metadata)},
        ),
        artifacts,
        parents=(ParentLink(alpha_run_id, "alpha_input"),),
    )
    return run_id


def frame_digest(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(str(tuple(str(value) for value in frame.columns)).encode("utf-8"))
    digest.update(np.ascontiguousarray(frame.index.view("int64")).tobytes())
    digest.update(np.ascontiguousarray(frame.to_numpy()).tobytes())
    return digest.hexdigest()
