from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path


INTEGRATION_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = INTEGRATION_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(INTEGRATION_ROOT))

from peer_momentum_runtime.runner import run_qlib_peer_momentum


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the peer momentum migration twin in Qlib's strategy/executor loop."
    )
    parser.add_argument("--start-date", default="2025-01-02")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "native_peer_momentum",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_qlib_peer_momentum(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
    )
    print(json.dumps(result.summary, ensure_ascii=False, indent=2, default=str))
    print(f"Wrote Qlib peer momentum artifacts to {result.output_dir}")


if __name__ == "__main__":
    main()
