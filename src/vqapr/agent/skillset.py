"""출하하는 skill 집합과, 설치본이 어디서 왔는지에 대한 판정.

PRD §11.2가 skill을 집합으로 정하고 §11.3이 그 집합의 설치본을 어떻게 판정하는지 정했다. 이
모듈이 그 판정을 소유한다 -- `cli/skill.py`는 동사와 봉투만 담당한다.

판정이 CLI 안에 있으면 안 되는 이유는 record `168`이 정한 그대로다: CLI만 묻는 판정은 결함이다.
낡은 skill이 해를 끼치는 순간은 `vqapr skill list`를 부를 때가 아니라 agent가 그것을 읽고
**다른** 명령을 실행할 때이므로, 판정은 공유 경로에 있어야 하고 부르는 쪽이 여럿이어야 한다.

## 왜 manifest가 아니라 내용이 답하는가

"설치본이 우리가 준 그대로인가"를 manifest에 적힌 해시로 답하면, manifest가 없는 설치본은 답할
수 없다. 그런데 skill directory는 손으로 복사되거나 git으로 clone되어 manifest 없이 도착한다.
그래서 package가 **자기가 정식 릴리스에서 출하한 적 있는 모든 파일 내용의 해시**를 들고 다니고
(`_shipped.json`), 판정은 내용만 본다.

manifest는 다른 것을 안다 -- 이 프로젝트가 **무엇을 깔기로 했는가**. 해시를 양쪽에 두면 둘 중
하나는 반드시 어긋나므로 manifest에서 해시를 뺐다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata, resources
from pathlib import Path
from typing import Any

SKILLS_PACKAGE = "vqapr.agent.skills"

RELEASED_TABLE = "_shipped.json"
"""출하 이력. skill 안에서의 상대 경로 -> {sha256: 그 내용이 처음 출하된 릴리스}.

키가 릴리스 버전이 아니라 경로인 이유(PRD §11.2·§11.3): 버전으로 키를 잡으면 내용이 안 바뀐
skill도 릴리스마다 한 벌씩 쌓인다. 경로로 잡으면 내용이 실제로 바뀔 때만 항목이 늘고, 값에
릴리스를 적어두면 출처가 항목 수를 늘리지 않고 따라온다.

두 target에 같은 bytes가 설치되므로(PRD §11.2) 항목은 target별로 두 벌 필요하지 않다.
"""

MANIFEST_NAME = ".vqapr-skill.json"
"""설치가 남기는 의도 기록. 해시는 들어 있지 않다 -- 위 docstring의 이유."""

_NOT_A_SKILL = frozenset({"README.md", RELEASED_TABLE, "__init__.py", "__pycache__"})
"""`skills/` 최상위에서 skill directory가 아닌 이름.

`README.md`는 이 디렉터리를 유지보수하는 사람에게 하는 말이지 skill을 읽는 agent에게 하는 말이
아니다. 설치본에 섞이면 agent가 자기 대상이 아닌 문서를 권위로 읽는다.
"""


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def package_version() -> str:
    """설치된 distribution의 version, 읽을 수 없으면 표식.

    editable install도 version을 보고한다. version이 움직이지 않아도 내용 판정은 해시가 하므로
    이 값은 "언제 깔았나"의 기록이지 판정의 근거가 아니다.
    """
    try:
        return metadata.version("vqapr")
    except metadata.PackageNotFoundError:
        return "unknown"


def _walk(ref: Any, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    """resource tree를 훑어 (상대 posix 경로, 내용)을 낸다.

    경로 구분자는 항상 `/`다. Windows에서 만든 표가 Unix에서 읽히거나 그 반대가 되면 같은 파일이
    다른 키가 되고, 그러면 손대지 않은 설치본이 `modified`로 판정된다.
    """
    for item in sorted(ref.iterdir(), key=lambda i: i.name):
        if item.name in _NOT_A_SKILL:
            continue
        if item.is_dir():
            yield from _walk(item, f"{prefix}{item.name}/")
        elif item.is_file():
            yield f"{prefix}{item.name}", item.read_bytes()


def skills_in(root: Any) -> dict[str, dict[str, bytes]]:
    """어떤 뿌리 아래의 skill 전부. `{skill 이름: {상대 경로: 내용}}`.

    뿌리 하나가 `Traversable`이든 `Path`이든 같은 답을 내야 한다: 설치된 package는 전자로 읽히고
    릴리스 도구는 후자로 리포의 원본을 읽는다. 두 자리가 각자 훑으면 제외 목록이 갈라지고,
    그러면 릴리스가 기록한 목록과 판정이 보는 목록이 달라진다.
    """
    skills: dict[str, dict[str, bytes]] = {}
    for item in sorted(root.iterdir(), key=lambda i: i.name):
        if item.name in _NOT_A_SKILL or not item.is_dir():
            continue
        skills[item.name] = dict(_walk(item))
    return skills


def shipped_skills() -> dict[str, dict[str, bytes]]:
    """이 package가 출하하는 skill 전부.

    `__file__`을 걷지 않고 resource로 읽는 이유는 zipimport나 비전개 설치에서 path 형태가 예외를
    던지기 때문이다 -- 그러면 판정이 한 줄 봉투 대신 traceback이 된다.
    """
    return skills_in(resources.files(SKILLS_PACKAGE))


def released_hashes() -> dict[str, dict[str, str]]:
    """출하 이력 표. 표가 없으면 빈 표 -- 아직 아무것도 릴리스되지 않았다는 뜻이다.

    빈 표에서는 "출하한 적 있는 내용인가"가 언제나 아니오이므로, 지금 출하본과 다른 설치본은
    전부 `modified`가 된다. 릴리스 전 개발 중에는 그것이 맞는 답이다: 우리는 그 bytes를 준 적이
    없다.
    """
    ref = resources.files(SKILLS_PACKAGE) / RELEASED_TABLE
    if not ref.is_file():
        return {}
    loaded = json.loads(ref.read_text(encoding="utf-8"))
    return {str(key): dict(value) for key, value in loaded.items()}


class FileState(StrEnum):
    """한 파일에 대한 판정. PRD §11.3의 세 판정에 두 경계 상태를 더한다."""

    CURRENT = "current"
    """지금 출하본과 같다."""

    OUTDATED = "outdated"
    """다르지만 우리가 출하한 적 있는 내용이다. 이전 릴리스의 정본이므로 확인 없이 갱신한다."""

    MODIFIED = "modified"
    """우리가 출하한 어떤 판과도 다르다. 명시적 확인 없이 덮어쓰지 않는다."""

    ABSENT = "absent"
    """출하 대상인데 디스크에 없다. 쓰면 되고, 잃을 것이 없다."""

    UNKNOWN = "unknown"
    """우리가 출하한 적 없는 경로에 있다. 우리 것이 아니므로 보고만 하고 건드리지 않는다."""


WRITABLE_WITHOUT_FORCE = frozenset({FileState.CURRENT, FileState.OUTDATED, FileState.ABSENT})
"""확인 없이 써도 되는 상태.

`MODIFIED`가 빠진 것이 이 판정의 전부다 -- 거기에 사용자의 작업이 있다. `UNKNOWN`도 빠지지만
이유가 다르다: 그것은 우리가 쓸 자리가 아니라 애초에 우리 파일이 아니다.
"""


@dataclass(frozen=True)
class FileVerdict:
    path: str
    """skill 안에서의 상대 posix 경로."""

    state: FileState

    released_in: str | None = None
    """`OUTDATED`일 때 그 내용이 처음 출하된 릴리스. 나머지 상태에서는 None."""


@dataclass(frozen=True)
class SkillVerdict:
    name: str
    files: tuple[FileVerdict, ...]

    @property
    def state(self) -> FileState:
        """skill 전체의 상태. 가장 나쁜 파일이 대표한다.

        갱신 결정은 파일별로 내리지만(한 줄 고친 대가로 skill 전체가 잠기면 안 된다) 사람에게
        한 단어로 말할 때는 주의가 필요한 쪽이 대표해야 한다.
        """
        states = {f.state for f in self.files}
        for candidate in (FileState.MODIFIED, FileState.OUTDATED, FileState.ABSENT):
            if candidate in states:
                return candidate
        return FileState.CURRENT

    @property
    def needs_force(self) -> tuple[str, ...]:
        """확인 없이는 덮어쓸 수 없는 경로."""
        return tuple(f.path for f in self.files if f.state is FileState.MODIFIED)

    @property
    def not_ours(self) -> tuple[str, ...]:
        """우리가 출하한 적 없는 경로. 제거 대상이 아니다."""
        return tuple(f.path for f in self.files if f.state is FileState.UNKNOWN)


def judge(
    name: str,
    installed: Mapping[str, bytes],
    *,
    shipped: Mapping[str, bytes],
    released: Mapping[str, Mapping[str, str]],
) -> SkillVerdict:
    """설치본 하나를 판정한다.

    순수 함수다 -- 디스크를 읽지 않고 bytes만 본다. 그래야 여섯 상태를 파일 없이 테스트할 수
    있고, 판정과 IO가 같은 자리에서 섞이지 않는다.
    """
    verdicts: list[FileVerdict] = []

    for path in sorted(shipped):
        content = installed.get(path)
        if content is None:
            verdicts.append(FileVerdict(path, FileState.ABSENT))
            continue
        if content == shipped[path]:
            verdicts.append(FileVerdict(path, FileState.CURRENT))
            continue
        known = released.get(f"{name}/{path}", {})
        release = known.get(sha256(content))
        if release is None:
            verdicts.append(FileVerdict(path, FileState.MODIFIED))
        else:
            verdicts.append(FileVerdict(path, FileState.OUTDATED, released_in=release))

    for path in sorted(set(installed) - set(shipped)):
        verdicts.append(FileVerdict(path, FileState.UNKNOWN))

    return SkillVerdict(name=name, files=tuple(verdicts))


def read_manifest(path: Path) -> dict[str, Any] | None:
    """설치 의도 기록을 읽는다. 없거나 읽을 수 없으면 None.

    깨진 manifest를 예외로 만들지 않는 이유: manifest는 판정의 근거가 아니라 "무엇을 깔기로
    했는가"의 기록이므로, 그것이 없어도 내용 판정은 그대로 성립한다. 여기서 던지면 복구 가능한
    상태에서 명령 전체가 죽는다.
    """
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def upgrade_note(root: Path, manifest_name: str = MANIFEST_NAME) -> str | None:
    """설치본이 다른 package version에서 왔으면 그 사실을 한 줄로. 아니면 None.

    모든 명령이 부르는 싼 검사다 -- manifest 하나를 읽고 문자열을 비교할 뿐 해시를 계산하지
    않는다. 전량 판정은 `vqapr skill list`가 한다.

    editable install에서 version이 움직이지 않은 채 내용만 바뀐 경우는 이 검사가 놓친다. 그것은
    package를 직접 고치고 있는 사람의 환경이고, 그 사람은 자기가 무엇을 바꿨는지 안다.
    """
    for parent in (root / ".agents" / "skills", root / ".claude" / "skills"):
        manifest = read_manifest(parent / manifest_name)
        if manifest is None:
            continue
        installed_from = manifest.get("package_version")
        current = package_version()
        if installed_from and installed_from != current:
            return (
                f"the agent skills in {parent} were installed from vqapr {installed_from}; "
                f"this is {current}. Run `vqapr skill install` to update them."
            )
    return None
