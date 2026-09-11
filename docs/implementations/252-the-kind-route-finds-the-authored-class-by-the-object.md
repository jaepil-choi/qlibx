# 252 — `register <kind>`가 저자 클래스를 객체로 찾고, 옆 파일 import를 이유로 거절한다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-register-by-kind-refuses-a-strategy-that-inherits-through-a-shared-base-and-its-fix-names-a-class-already-there.md`, `docs/issues/report-2026-09-11-a-component-cannot-import-a-module-beside-it-and-the-502-fix-does-not-say-why.md` |
| **설계 근거** | 오너 판정 2026-09-04 "전략 하나 = 파일 하나"(`docs/issues/archive/065`), AC-A4(거절은 COUNT를 댄다), 기록 `009`(fingerprint는 gate가 아니라 receipt) |
| **브랜치** | `develop` |
| **앞선 기록** | `065`, `112`, `196` |

---

## 왜 이 변경이 있는가

FF3 testbed의 에이전트가 여섯 leg를 공통 base로 썼다 — `strategy_common.py`에 `Ff3Portfolio`, leaf 파일마다
`class Ff3S1(strategy_common.Ff3Portfolio)` 한 줄. `vqapr register strategy ff3-s1 strategy_S1.py`는 여섯 번 다
`the file must define exactly one StrategyModel subclass`, `observed: "defines 0"`, `fix: "add a
\`class Ff3S1(StrategyModel):\` to strategy_S1.py"` — **파일이 이미 가진 클래스를 추가하라**는 말이었고,
그대로 따르면 파일이 둘을 정의하게 된다. 같은 파일을 YAML로(`object_name: Ff3S1`) 선언하면 등록된다.
두 route가 같은 파일에 반대 판정을 냈다.

원인: `_sole_subclass`가 base를 **이름으로** 찾는다. `strategy_common.Ff3Portfolio`는 이 파일이 정의하지도,
authoring 이름으로 import하지도 않은 이름이라 매치가 없다. YAML route는 파일을 로드해 **객체로** 판정한다.

그 옆에서 같은 에이전트가 부딪힌 두 번째 것: 컴포넌트가 자기 디렉터리의 모듈을 `import`하면 502
`ModuleNotFoundError`이고, `fix`는 "생성 중 난 예외를 고쳐라"였다 — 파일 위치로 보면 맞는 import를 고치라는 말.

## 무엇이 어떻게 바뀌었는가

- `extension/loading.py`: 컴포넌트 소스를 실행하는 문 하나(`_execute`)로 모았다. `_load`가 그 위에서 객체를
  만들고, 새 `authored_classes(path, kind)`가 그 모듈에서 **객체로** leaf 클래스를 찾는다(이 파일이 정의했고
  (`__module__`), 그 kind의 base를 상속하며, 이 파일의 다른 클래스가 상속하지 않는 것).
- `project/registration.py::_sole_subclass`: 파싱이 먼저다(파일에 전략이 둘이면 "둘"로 거절하는 성질은 그대로).
  파싱이 **하나도 못 찾았고**, 이 파일이 정의하지 않은 이름을 base로 쓰는 클래스가 있을 때만 `authored_classes`에
  묻는다. base가 import되지 않으면 YAML route와 같은 거절(502, `component.construction_failed`)이 나온다.
- `_construction_fix`: `ModuleNotFoundError`의 모듈이 **컴포넌트 옆에 실제로 있을 때만** 이유를 말한다 —
  "`helper`가 옆에 있지만 컴포넌트 디렉터리는 import 경로가 아니다; 컴포넌트는 파일 하나이고 fingerprint도
  그 파일만 덮는다. 공유 코드는 이 파일 안에, 또는 환경에 설치된 패키지(혹은 PYTHONPATH)로." 그 밖의
  `ModuleNotFoundError`는 저자의 빠진 의존성이므로 문구가 그대로다.
- skill 둘: make-strategy의 "One strategy is one file"에 한 문단, make-datamodel의 scaffold 절에 한 문장.

## 바꾸지 않은 것

"파일 하나 = 컴포넌트 하나" 규칙 자체(오너 판정). 컴포넌트 디렉터리를 `sys.path`에 넣지 **않는다** — 넣으면
옆 모듈이 바뀌어도 fingerprint가 안 변해 receipt가 조용히 틀린다(2026-09-11 오너 판정). 파싱이 "둘"을
거절하는 경로, AC-A4의 COUNT 문구.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/extension/test_authoring_contract.py::test_a_leaf_through_an_imported_base_is_found_by_the_object` (신규) | 공유 base를 import한 leaf + 무관한 `NamedTuple` → `Leg` |
| 같은 파일 `test_a_base_beside_the_component_is_named_as_why_it_does_not_import` (신규) | base가 옆에 있고 import 불가 → 502 `component.construction_failed`, `fix`가 이름과 이유를 댐 |
| 같은 파일 `test_registering_a_component_that_imports_its_neighbour_names_the_rule` (신규) | 로더 경로(FF3가 실제로 만난 자리)에서 같은 `fix` |
| 기존 `test_the_authored_class_is_found_however_it_was_written` 넷(plain·aliased·상속 사슬·nested)과 "defines 0"·"defines 2" | 통과 — 파싱 경로는 그대로 |
| `tests/extension tests/boundaries tests/project` | 170 passed (경계 테스트: `project` → `extension` import는 기존 방향) |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
