"""릴리스가 출하하는 skill 내용의 해시를 `_shipped.json`에 적는다.

PRD §11.3. 이 표가 "설치본이 우리가 준 것인가"의 유일한 근거이므로, **릴리스 때마다 이 스크립트가
돌아야 한다.** 안 돌면 다음 릴리스에서 그 판을 설치해둔 사용자가 손대지 않았는데 `modified`
판정을 받고, `--force`를 습관으로 배운다 -- 판정이 막으려던 바로 그 습관이다.

    uv run python scripts/record_shipped_skills.py --check     기록되지 않은 내용이 있으면 1
    uv run python scripts/record_shipped_skills.py             현재 내용을 현재 version으로 기록

`--check`가 릴리스 절차의 게이트다. `.agents/skills/package-release/SKILL.md`가 그 자리를 정한다.

## 항목을 지우지 않는다

이 스크립트는 **추가만** 한다. 어떤 파일이 출하 목록에서 빠져도 그 파일의 과거 해시는 표에
남는다. 그것을 지우면 그 파일을 아직 들고 있는 설치본이 `modified`가 되고, 사실 그 설치본은
우리가 준 그대로다. 표는 "지금 무엇을 출하하는가"가 아니라 "무엇을 출하한 적 있는가"의 기록이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from vqapr.agent.skillset import RELEASED_TABLE, sha256, skills_in  # noqa: E402

SKILLS = REPO / "src" / "vqapr" / "agent" / "skills"
TABLE = SKILLS / RELEASED_TABLE


def _current_release() -> str:
    """`pyproject.toml`이 선언한 version.

    설치된 distribution의 metadata가 아니라 선언을 읽는다. 릴리스 절차는 version을 올린 **뒤**
    빌드하므로, 이 스크립트가 돌 때 설치된 metadata는 아직 이전 version일 수 있다.
    """
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("pyproject.toml declares no version")


def _load() -> dict[str, dict[str, str]]:
    if not TABLE.is_file():
        return {}
    return json.loads(TABLE.read_text(encoding="utf-8"))


def _current_entries() -> dict[str, str]:
    """`{"<skill>/<상대 경로>": sha256}` — 지금 출하되는 내용."""
    return {
        f"{name}/{path}": sha256(content)
        for name, files in skills_in(SKILLS).items()
        for path, content in files.items()
    }


def main(argv: list[str] | None = None) -> int:
    # ASCII on purpose. argparse writes `--help` through the inherited console encoding, and cp949
    # on a Korean Windows console cannot encode this module's docstring -- the reasoning stays up
    # there for whoever maintains the script, and what reaches a terminal stays printable.
    parser = argparse.ArgumentParser(
        description=(
            "Record the sha256 of every skill file this release ships, so a later release can "
            "tell an outdated install from an edited one."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report unrecorded content and exit non-zero instead of recording it",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="label to record new content under (default: the version in pyproject.toml)",
    )
    args = parser.parse_args(argv)

    table = _load()
    release = args.release or _current_release()

    missing = {
        key: digest
        for key, digest in _current_entries().items()
        if digest not in table.get(key, {})
    }

    if args.check:
        if not missing:
            print(f"every shipped skill file is recorded (release {release})")
            return 0
        print(
            f"{len(missing)} shipped skill file(s) are not in {TABLE.name}. Users upgrading past "
            f"release {release} would be told their untouched copies were edited.\n"
            "Record them with:\n"
            "  uv run python scripts/record_shipped_skills.py",
            file=sys.stderr,
        )
        for key in sorted(missing):
            print(f"  {key}", file=sys.stderr)
        return 1

    for key, digest in missing.items():
        table.setdefault(key, {})[digest] = release
    TABLE.write_text(
        json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"recorded {len(missing)} new content hash(es) under release {release} in {TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
