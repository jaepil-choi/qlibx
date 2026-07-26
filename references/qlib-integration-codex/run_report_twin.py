from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


INTEGRATION_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = INTEGRATION_ROOT.parent
sys.path.insert(0, str(INTEGRATION_ROOT))

from report_twin import run_report_twin  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce every report-draft-3 alpha and ensemble as a Qlib twin."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "report_twin",
    )
    parser.add_argument("--skip-qlib-execution", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_report_twin(
        project_root=PROJECT_ROOT,
        output_dir=args.output_dir,
        execute_qlib=not args.skip_qlib_execution,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
