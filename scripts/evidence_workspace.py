"""슬라이스 4 증거 — 등록 선언이 project workspace에서 명령 사이에 살아남는다.

uv run python scripts/evidence_workspace.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from vqapr.workspace import Workspace

from vqapr.data.dataset import DatasetRegistration, validate
from vqapr.data.source import SourceSpec
from vqapr.domain.errors import VqaprError

DEV = Path("data/vqapr-dev/price_daily")


def registration(raw_id: str = "price_daily", *, close: str = "종가") -> DatasetRegistration:
    return DatasetRegistration.of(
        raw_id,
        "fng_prices",
        instrument_field="종목약코드",
        available_at="available_at",
        key_fields=("거래일자", "종목약코드"),
        fields={"close": close, "session_date": "거래일자"},
    ).with_span(
        # These scripts exercise workspace persistence against a fixed declaration rather than a
        # real scan, so the span is supplied instead of measured. Persistence requires one.
        datetime(2024, 1, 2, 15, 30, tzinfo=UTC),
        datetime(2025, 1, 2, 15, 30, tzinfo=UTC),
    )


def source() -> SourceSpec:
    return SourceSpec.of("fng_prices", DEV, hive_partitioned=True)


def child(mode: str, project_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), f"--{mode}", str(project_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def child_main(args: argparse.Namespace) -> int | None:
    if args.write_first:
        workspace = Workspace.create(args.write_first)
        return emit(
            {
                "pid": os.getpid(),
                "changed": workspace.register_dataset(registration(), source()),
                "workspace": str(workspace.path),
            }
        )
    if args.write_second:
        workspace = Workspace.open(args.write_second)
        return emit(
            {
                "pid": os.getpid(),
                "changed": workspace.register_dataset(registration("price_adjusted"), source()),
                "datasets": [str(item.dataset_id) for item in workspace.datasets],
            }
        )
    if args.read:
        try:
            workspace = Workspace.open(args.read)
            stored_source = workspace.source("fng_prices")
            return emit(
                {
                    "pid": os.getpid(),
                    "datasets": [str(item.dataset_id) for item in workspace.datasets],
                    "price_daily_equal": workspace.dataset("price_daily") == registration(),
                    "source_equal": stored_source == source(),
                    "source_path": str(stored_source.path),
                    "hive_partitioned": stored_source.hive_partitioned,
                }
            )
        except VqaprError as error:
            return emit({"pid": os.getpid(), "error": error.as_dict()})
    if args.retry_same:
        workspace = Workspace.open(args.retry_same)
        return emit(
            {
                "pid": os.getpid(),
                "changed": workspace.register_dataset(registration(), source()),
            }
        )
    if args.conflict:
        workspace = Workspace.open(args.conflict)
        try:
            workspace.register_dataset(registration(close="수정종가"), source())
        except VqaprError as error:
            return emit({"pid": os.getpid(), "error": error.as_dict()})
        raise AssertionError("conflicting declaration unexpectedly succeeded")
    if args.write_isolated:
        workspace = Workspace.create(args.write_isolated)
        changed = workspace.register_dataset(registration("fundamentals"), source())
        return emit(
            {
                "pid": os.getpid(),
                "changed": changed,
                "datasets": [str(item.dataset_id) for item in workspace.datasets],
            }
        )
    if args.stale_merge:
        current = Workspace.create(args.stale_merge)
        current.register_dataset(registration("one"), source())
        stale = Workspace.open(args.stale_merge)
        current.register_dataset(registration("two"), source())
        stale.register_dataset(registration("three"), source())
        return emit(
            {
                "pid": os.getpid(),
                "datasets": [
                    str(item.dataset_id) for item in Workspace.open(args.stale_merge).datasets
                ],
            }
        )
    if args.deleted_workspace:
        workspace = Workspace.create(args.deleted_workspace)
        item = registration()
        workspace.register_dataset(item, source())
        workspace.path.unlink()
        try:
            workspace.register_dataset(item, source())
        except VqaprError as error:
            return emit(
                {
                    "pid": os.getpid(),
                    "path_exists": workspace.path.exists(),
                    "error": error.as_dict(),
                }
            )
        raise AssertionError("registration against a deleted workspace unexpectedly succeeded")
    if args.lookup_errors:
        workspace = Workspace.open(args.lookup_errors)
        errors: dict[str, object] = {}
        for label, lookup in (
            ("invalid_dataset", lambda: workspace.dataset("bad id")),
            ("missing_dataset", lambda: workspace.dataset("missing")),
            ("missing_source", lambda: workspace.source("missing")),
        ):
            try:
                lookup()
            except VqaprError as error:
                errors[label] = error.as_dict()
        return emit({"pid": os.getpid(), "errors": errors})
    return None


def heading(number: int, title: str) -> None:
    print(f"\n{'=' * 78}\n[{number}] {title}\n{'=' * 78}")


def main() -> int:
    if not DEV.exists():
        print(f"missing {DEV} — run scripts/prepare_dev_data.py first")
        return 1

    heading(1, "실데이터 선언을 먼저 검증한다")
    diagnosis, timing, _measured = validate(registration(), source())
    diagnosis.raise_if_failed()
    print(
        f"ok={diagnosis.ok}  schema={timing.schema_seconds:.2f}s  "
        f"key={timing.key_seconds:.2f}s  key_was_skipped={timing.key_was_skipped}"
    )

    with tempfile.TemporaryDirectory(prefix="vqapr-workspace-evidence-") as temporary:
        root = Path(temporary) / "project-a"

        heading(2, "프로세스 A에서 등록하고 프로세스 B에서 같은 선언을 조회한다")
        written = child("write-first", root)
        reopened = child("read", root)
        assert written["pid"] != reopened["pid"]
        assert written["changed"] is True
        assert reopened["price_daily_equal"] is True
        assert reopened["source_equal"] is True
        assert reopened["hive_partitioned"] is True
        print(f"writer_pid={written['pid']}  reader_pid={reopened['pid']}")
        print(f"round_trip_equal={reopened['price_daily_equal']}")
        print(
            f"source_round_trip_equal={reopened['source_equal']}  "
            f"path={reopened['source_path']}  hive_partitioned={reopened['hive_partitioned']}"
        )
        print(f"workspace={written['workspace']}")

        heading(3, "두 번째 dataset을 더해도 둘 다 남는다")
        second = child("write-second", root)
        both = child("read", root)
        assert both["datasets"] == ["price_adjusted", "price_daily"]
        print(f"dataset_count={len(both['datasets'])}  datasets={both['datasets']}")
        print(f"writer_pid={second['pid']}  reader_pid={both['pid']}")

        heading(4, "같은 선언의 재등록은 idempotent no-op이다")
        same = child("retry-same", root)
        assert same["changed"] is False
        print(f"changed={same['changed']}  pid={same['pid']}")

        heading(5, "같은 dataset_id의 다른 선언은 mutation 없이 실패한다")
        conflict = child("conflict", root)
        error = conflict["error"]
        assert error["mutation"] is False
        assert error["failures"][0]["code"] == "workspace.dataset.register.conflict"
        print(json.dumps(error, ensure_ascii=False, indent=2))

        heading(6, "없는 workspace와 손상된 YAML은 파싱 가능한 실패다")
        missing = child("read", Path(temporary) / "missing")
        missing_error = missing["error"]
        assert missing_error["failures"][0]["code"] == "workspace.open.missing"
        print("missing:")
        print(json.dumps(missing_error, ensure_ascii=False, indent=2))

        corrupt_root = Path(temporary) / "corrupt"
        corrupt_path = corrupt_root / ".vqapr" / "workspace.yaml"
        corrupt_path.parent.mkdir(parents=True)
        corrupt_path.write_text("datasets: [not, a, mapping]", encoding="utf-8")
        corrupt = child("read", corrupt_root)
        corrupt_error = corrupt["error"]
        assert corrupt_error["failures"][0]["code"] == "workspace.open.invalid"
        print("corrupt:")
        print(json.dumps(corrupt_error, ensure_ascii=False, indent=2))

        heading(7, "명시적으로 고른 두 project workspace는 서로 섞이지 않는다")
        other_root = Path(temporary) / "project-b"
        isolated = child("write-isolated", other_root)
        first_after = child("read", root)
        assert isolated["datasets"] == ["fundamentals"]
        assert first_after["datasets"] == ["price_adjusted", "price_daily"]
        print(f"project_a={first_after['datasets']}")
        print(f"project_b={isolated['datasets']}")
        print("shared_global_state=false")

        heading(8, "오래된 인스턴스도 디스크에 추가된 dataset을 지우지 않는다")
        stale = child("stale-merge", Path(temporary) / "stale")
        assert stale["datasets"] == ["one", "three", "two"]
        print(f"datasets_after_stale_write={stale['datasets']}")

        heading(9, "삭제된 workspace와 잘못된 조회는 파싱 가능한 실패다")
        deleted = child("deleted-workspace", Path(temporary) / "deleted")
        deleted_error = deleted["error"]
        assert deleted["path_exists"] is False
        assert deleted_error["failures"][0]["code"] == "workspace.open.missing"
        print("deleted_workspace:")
        print(json.dumps(deleted_error, ensure_ascii=False, indent=2))

        lookup = child("lookup-errors", root)
        lookup_errors = lookup["errors"]
        assert lookup_errors["invalid_dataset"]["failures"][0]["code"] == (
            "workspace.dataset.lookup.invalid"
        )
        assert lookup_errors["missing_dataset"]["failures"][0]["code"] == (
            "workspace.dataset.lookup.missing"
        )
        assert lookup_errors["missing_source"]["failures"][0]["code"] == (
            "workspace.source.lookup.missing"
        )
        print("lookup_errors:")
        print(json.dumps(lookup_errors, ensure_ascii=False, indent=2))

    print("\n" + "=" * 78)
    print("모든 workspace 시나리오 실행 완료")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-first", type=Path)
    parser.add_argument("--write-second", type=Path)
    parser.add_argument("--read", type=Path)
    parser.add_argument("--retry-same", type=Path)
    parser.add_argument("--conflict", type=Path)
    parser.add_argument("--write-isolated", type=Path)
    parser.add_argument("--stale-merge", type=Path)
    parser.add_argument("--deleted-workspace", type=Path)
    parser.add_argument("--lookup-errors", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    result = child_main(parsed)
    sys.exit(main() if result is None else result)
