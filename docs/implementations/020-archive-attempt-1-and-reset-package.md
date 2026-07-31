# Attempt 1 보존과 root package 초기화

## 배경과 목적

첫 번째 qlibx 구현은 Qlib을 핵심 runtime으로 충분히 활용하지 못했다. 이 상태에서 기존 구조를 점진적으로
수정하면 구현의 우연한 책임 분리와 public contract를 계속 끌고 갈 가능성이 높다. 따라서 첫 구현을 삭제하지
않고 `attempts/attempt-1/`에 재현 가능한 reference로 보존하고, repository root는 새 canonical PRD를 기준으로
다시 설계할 수 있는 최소 package 상태로 초기화했다.

## 책임과 flow 변경

- Attempt 1의 source, config, tests, examples, package metadata와 lockfile을
  `attempts/attempt-1/` 아래로 격리했다.
- `docs/` 전체, 외부 `references/`, 공용 source data, runtime state와 repository workflow는 root에
  유지했다.
- Root runtime은 dependency가 없는 최소 `src/qlibx/__init__.py`와 console entry point만 남겼다.
- Attempt 2 기능은 구현하지 않았다. 새 PRD에서 architecture와 public contract를 다시 도출하는 것이 다음
  작업이다.

## 대안과 trade-off

Git history만으로 attempt 1을 보존하는 방법은 현재 파일을 직접 비교하기 어렵다. 반대로 docs, ignored data,
virtualenv, cache와 external reference까지 archive에 복제하면 범위가 불필요하게 커진다. 따라서 구현 code와
package state만 archive하고 나머지는 root에 유지했다.

초기 `uv init --package` commit은 Python 3.13을 사용했지만 새 PRD의 Qlib 0.9.7 baseline과 맞지 않는다.
그러므로 최소 scaffold는 유지하되 Python 범위는 `>=3.10,<3.13`, local interpreter는 3.12로 유지했다.

## 검증

- Archive 이동 직후 local canonical data를 임시로 포함해
  `UV_PROJECT_ENVIRONMENT=<root>/.venv uv run --locked pytest`를 실행했고
  `164 passed, 35 warnings`를 확인했다. 사용자 범위 재확인 후 해당 data와 cache는 archive에서 제거했다.
- `uv lock --check`: 통과. Root lock graph는 dependency 없는 editable `qlibx` 하나다.
- `uv tree --locked`: `qlibx v0.1.0`.
- `PYTHONPATH=src uv run --no-sync --locked python -c "import qlibx; ..."`:
  root `src/qlibx/__init__.py`를 import하고 `Hello from qlibx!`를 출력했다.
- `uv run --no-sync --locked python -m compileall -q src`: 통과. 생성 bytecode는 제거했다.
- `uv build --out-dir C:\tmp\qlibx-reset-build-20260731`: wheel과 sdist 생성에 성공했다.
- `uv sync --locked`는 기존 `.venv\Scripts\ruff.exe` 제거 단계에서 Windows `os error 5`로 두 번
  중단됐다. 사용자가 venv를 이동·정리 범위에서 제외했으므로 추가 mutation 없이 `--no-sync` 검증으로
  전환했다.

## 남은 제약과 후속 작업

- Attempt 2의 dependency, tests, architecture와 public API는 아직 정하지 않았다.
- `attempts/attempt-1/`은 frozen reference이며 신규 구현을 추가하지 않는다.
