"""슬라이스 5 증거 — public surface만으로 실데이터를 등록한다.

uv run python scripts/evidence_public.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from vqapr.public import DatasetRegistration, SourceSpec, VqaprError, register_dataset

DEV = Path("data/vqapr-dev/price_daily")


def registration(*, close: str = "종가", weak_key: bool = False) -> DatasetRegistration:
    key_fields = ("종목약코드",) if weak_key else ("거래일자", "종목약코드")
    return DatasetRegistration.of(
        "price_daily",
        "fng_prices",
        instrument_field="종목약코드",
        available_at="available_at",
        key_fields=key_fields,
        fields={"close": close, "session_date": "거래일자"},
    )


def source() -> SourceSpec:
    return SourceSpec.of("fng_prices", DEV, hive_partitioned=True)


def emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def child(mode: str, project_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), f"--{mode}", str(project_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def capture(project_root: Path, item: DatasetRegistration, spec: SourceSpec) -> dict[str, object]:
    try:
        changed = register_dataset(project_root, item, spec)
        return {
            "pid": os.getpid(),
            "changed": changed,
            "workspace_exists": (project_root / ".vqapr" / "workspace.yaml").is_file(),
        }
    except VqaprError as error:
        return {
            "pid": os.getpid(),
            "workspace_exists": (project_root / ".vqapr").exists(),
            "error": error.as_dict(),
        }


def child_main(args: argparse.Namespace) -> int | None:
    if args.register:
        return emit(capture(args.register, registration(), source()))
    if args.bad_schema:
        return emit(capture(args.bad_schema, registration(close="없는컬럼"), source()))
    if args.weak_key:
        return emit(capture(args.weak_key, registration(weak_key=True), source()))
    if args.mismatch:
        missing = args.mismatch / "source-does-not-exist"
        payload = capture(
            args.mismatch,
            registration(),
            SourceSpec.of("other", missing, hive_partitioned=True),
        )
        payload["source_path_exists"] = missing.exists()
        return emit(payload)
    return None


def heading(number: int, title: str) -> None:
    print(f"\n{'=' * 78}\n[{number}] {title}\n{'=' * 78}")


def show_error(label: str, payload: dict[str, object], expected_code: str) -> None:
    error = payload["error"]
    assert error["mutation"] is False
    assert error["failures"][0]["code"] == expected_code
    assert payload["workspace_exists"] is False
    print(f"{label}: workspace_exists={payload['workspace_exists']}")
    print(json.dumps(error, ensure_ascii=False, indent=2))


def main() -> int:
    if not DEV.exists():
        print(f"missing {DEV} — run scripts/prepare_dev_data.py first")
        return 1

    print("consumer_vqapr_import=vqapr.public")
    with tempfile.TemporaryDirectory(prefix="vqapr-public-evidence-") as temporary:
        temporary_root = Path(temporary)
        project = temporary_root / "project"

        heading(1, "프로세스 A가 등록하고 프로세스 B의 같은 요청은 idempotent하다")
        first = child("register", project)
        second = child("register", project)
        assert first["pid"] != second["pid"]
        assert first["changed"] is True
        assert second["changed"] is False
        assert first["workspace_exists"] is True
        assert second["workspace_exists"] is True
        print(f"first_pid={first['pid']}  changed={first['changed']}")
        print(f"second_pid={second['pid']}  changed={second['changed']}")
        print("persisted_across_processes=true")

        heading(2, "스키마 실패는 workspace를 만들지 않고 파싱 가능하게 끝난다")
        bad_schema = child("bad-schema", temporary_root / "bad-schema")
        show_error("bad_schema", bad_schema, "dataset.field_missing")

        heading(3, "약한 logical key도 workspace를 만들지 않는다")
        weak_key = child("weak-key", temporary_root / "weak-key")
        show_error("weak_key", weak_key, "dataset.key_duplicate")

        heading(4, "source ID 불일치는 존재하지 않는 path를 열기 전에 실패한다")
        mismatch = child("mismatch", temporary_root / "mismatch")
        assert mismatch["source_path_exists"] is False
        show_error("source_mismatch", mismatch, "dataset.source_mismatch")
        print(f"source_path_exists={mismatch['source_path_exists']}")

    print("\n" + "=" * 78)
    print("모든 public facade 시나리오 실행 완료")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", type=Path)
    parser.add_argument("--bad-schema", type=Path)
    parser.add_argument("--weak-key", type=Path)
    parser.add_argument("--mismatch", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    result = child_main(parsed)
    sys.exit(main() if result is None else result)
