# 273 — 명령과 명령 사이에 남는 것은 workspace다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M6 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §11 · §13 · §17, 오너 결정 (2026-09-11: 새로 지은 이름 `workspace/registry.py` 승인) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `271` · `272`(component) |

---

## 왜 이 변경이 있는가

`project/`는 `.vqapr/workspace.yaml` 한 파일과 그 파일에 쓰는 규칙을 담고 있었다. 사용자가 부르는 이름
(`Workspace`, `workspace.yaml`, `vqapr rm` 의 "workspace에서 지운다")과 패키지 이름이 달랐다. 안의 세 파일 이름도
하는 일을 말하지 않았다.

- `store.py`: 실제로는 등록된 선언을 열고 · 조회하고 · 잠금 아래 한 트랜잭션으로 쓰는 Registry다(Fowler의 Registry).
- `document.py`: 선언 문서의 모양, 즉 declarations다.
- `run.py`: run을 돌리지 않는다. run 하나의 정의(`RunDefinition`)다.

"project"는 사용자의 폴더 전체를 가리키는 말이기도 해서, 코드의 한 층 이름으로 쓰면 둘이 섞였다.

## 무엇이 어떻게 바뀌었는가

| 옛 자리 | 새 자리 |
|---|---|
| `project/store.py` | `workspace/registry.py` (`Workspace`, `Transaction`) |
| `project/document.py` | `workspace/declarations.py` |
| `project/run.py` | `workspace/run_definition.py` (`RunDefinition`) |
| `project/registration.py` · `merge.py` · `references.py` · `state.py` · `refusals.py` | `workspace/`의 같은 이름 |

- 옮긴 것은 모듈 통째라, import · 모듈 import(`from vqapr.project import store as ...`) · monkeypatch 문자열 · 경로를
  적은 문장을 한 번의 정규식으로 옮겼다. showcase 파일은 한 바이트도 바뀌지 않았다.
- `project/`에는 `__init__.py`가 없었다(namespace 패키지). `workspace/`는 무엇이 들어 있는지 말하는 docstring을
  가진 보통 패키지다.
- 층 표: `"project": 50` → `"workspace": 50`. 최종 층 번호는 M10에서 정한다.
- 테스트: `tests/project/test_run.py` → `tests/workspace/test_run_definition.py`. 루트의 `tests/test_workspace*.py`
  넷은 옮기지 않았다(이름이 이미 주제를 말하고, 옮기면 `__file__` 기준 경로만 흔든다).

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1796 통과 · 5 skip (208 s) |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 (옮긴 경로로 길어진 docstring 세 줄을 다시 감쌈) |
| `uv run pyright` | 0 errors, 0 warnings |
