"""Measure how per-publish cost scales with catalog size."""

import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from qlibx.evidence import ArtifactContract
from qlibx.evidence.local import LocalArtifactBackend
from qlibx.models import QlibxModel


class Payload(QlibxModel):
    index: int
    filler: str


def main() -> None:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    mode = sys.argv[2] if len(sys.argv) > 2 else "operation"
    if mode not in {"operation", "session"}:
        raise SystemExit("mode must be 'operation' or 'session'")
    bucket = max(total // 8, 1)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        catalog = LocalArtifactBackend(root / "catalog.duckdb", root / "artifacts")
        scope = catalog.session() if mode == "session" else nullcontext()
        print(f"mode={mode}")
        with scope:
            window_start = time.perf_counter()
            print(f"{'published':>10} {'ms/publish':>12}")
            for index in range(total):
                outcome = catalog.publish_model(
                    logical_identity=f"identity-{index}",
                    artifact_type="bench",
                    artifact_schema_version=1,
                    producer_id="bench",
                    payload=Payload(index=index, filler="x" * 256),
                )
                assert outcome.status.value == "complete", outcome
                if (index + 1) % bucket == 0:
                    elapsed = time.perf_counter() - window_start
                    print(f"{index + 1:>10} {elapsed / bucket * 1000:>12.1f}")
                    window_start = time.perf_counter()
            loaded = catalog.load_model(
                outcome.result.artifact_id,
                ArtifactContract(
                    artifact_type="bench",
                    artifact_schema_version=1,
                    payload_model=Payload,
                ),
            )
            assert loaded.status.value == "complete", loaded
            assert loaded.result.payload.index == total - 1


if __name__ == "__main__":
    main()