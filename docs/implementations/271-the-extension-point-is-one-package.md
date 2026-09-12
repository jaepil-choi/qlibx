# 271 — 확장 지점은 한 패키지다: `component/`

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M5a — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §6 · §17, 오너 결정 D3 · D8 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `268`(domain), `269`(data · record), `270`(signals · portfolio) |

---

## 왜 이 변경이 있는가

사용자 코드가 맡을 수 있는 역할은 넷이다: DataModel, StrategyModel, Exchange, Compliance. 그런데 그 계약과 구현이 네
패키지에 흩어져 있었다.

- `authoring/`: 계약 셋과 결과 값. 파일 이름은 `call.py` · `component.py` · `result.py`처럼 역할이 아니라 모양을 따랐다.
- `exchange/`: 네 번째 역할의 base와 학술용 구현이 `venue.py` 한 파일에 같이 있었다.
- `compliance/`: 규칙 집합의 평가, 그리고 `builtin/` 아래 출하 규칙 둘.
- `extension/`: 컴포넌트가 들어오는 문(참조 · 지문 · 적재 · 규격 검사 · 등록 준비 · scaffold).

오너가 짚은 것은 이 가운데 둘이다. "base class가 구현과 한 파일에 있다", "파일 이름과 실제로 하는 일이 너무 다르다".
결정 D3은 Component 추상화를 폴더에서도 이어 가는 것이었다. 한 패키지 `component/`를 두고, 그 안에서 역할마다 모듈
하나를 두며, base는 어떤 출하 구현과도 파일을 나누지 않는다.

## 무엇이 어떻게 바뀌었는가

| 새 자리 | 무엇이 들어왔나 |
|---|---|
| `component/base.py` | `Component` · `Part` · `Tool` (`authoring/component.py`) |
| `component/datamodel.py` | `DataCall` + `DataModel` |
| `component/strategy/base.py` · `decision.py` | `StrategyCall` + `StrategyModel` / `Hold` · `Rebalance` (`authoring/result.py`) |
| `component/strategy/history.py` · `recorder.py` | `authoring/history.py` · `records.py` (이름: 하는 일이 "레코드 쓰기"다) |
| `component/exchange/base.py` | `ExecutionCall` · `Exchange` (`exchange/venue.py`) + 모든 profile이 하는 요청 검사 셋(`requested_rows` · `validate_requests` · `accepted_requests`, `data/execution_table.py`에서) |
| `component/exchange/academic.py` · `krx.py` | `AcademicExchange` (`venue.py`에서 분리) · `exchange/venues/krx.py` |
| `component/compliance/base.py` | `ComplianceCall` · `Compliance` · `ComplianceFinding` |
| `component/compliance/report.py` | `StampedFinding` · `ComplianceReport` · 판정 상수 · 기본 허용오차 (`compliance/evaluation.py`에서) |
| `component/compliance/shipped.py` · `no_short.py` · `single_name_cap.py` | `compliance/builtin/__init__.py` · 출하 규칙 둘 |
| `component/reference.py` · `fingerprint.py` · `loading.py` | `extension/component.py` · `fingerprint.py` · `loading.py` |
| `component/conformance.py` | `extension/conformance.py` + `prepare.py` (등록 쪽 문과 규격 검사가 한 문이다) |
| `component/scaffold.py` | `extension/scaffold.py` + `lookback.py` |
| `component/reads.py` · `account_view.py` · `_validation.py` | `authoring/reads.py` · `view.py` · `_validation.py` |
| `flow/run/calls.py` | `authoring/context.py` — 엔진이 만들어 건네는 구체 call은 엔진의 것이다 |
| `flow/run/compliance.py` | OBSERVE 단계 + 규칙 집합의 평가 함수(`evaluate_compliance` · `build_account_view` · `compliance_requirements`) |

`exchange/`, `extension/`, `compliance/` 패키지는 사라졌다. `vqapr.authoring`은 이제 아무것도 정의하지 않고
`component`를 다시 내보내기만 한다. 0.15.0의 스킬 · scaffold · showcase가 쓰는 import 경로라서, 이름을 바꾸는 릴리스(M11,
오너 결정 3: `vqapr.public`으로 통일)까지만 남긴다.

- **`shipped.py`로 둔 이유.** 출하 규칙 찾기를 `component/compliance/__init__.py`에 두면, base 모듈을 import할 때마다
  출하 규칙이 먼저 실린다. 아키텍처 문서의 트리도 이에 맞게 고쳤다.
- **평가가 `flow/`로 올라간 이유.** 평가는 규칙마다 `ComplianceContext`(구체 call)를 만든다. 그 구체 call이
  `flow/run/calls.py`로 올라갔으니, 평가도 층 20에 머물 수 없다.
- **값이 단계와 떨어진 이유 (발견).** 실행 문맥(`flow/run/context.py`)은 `ComplianceReport`를 들고 다니고, OBSERVE
  단계는 그 문맥을 import한다. 값과 단계가 한 모듈에 있으면 import 순환이 생긴다. 목표 문서의 대응표도 같은 순환을
  품고 있었다(평가 → `stages/observe.py`). 그래서 값은 `component/compliance/report.py`로, 평가 함수만 단계로 가도록
  문서와 계획을 고쳤다.
- **층 표.** `component`는 20이다. 옮겨 온 모듈이 import하는 것은 모두 `domain` · `data` · `portfolio` · `record`(층
  10 이하) 아니면 `component` 자신이라, 층 하나로 합쳐도 위를 보는 import가 없다. 과도기 `authoring`은 21이고,
  `exchange` · `extension` · `compliance` 행은 지웠다.
- **바이트가 그대로인 것.** 출하 sample 전략(`agent/sample/reversal_5d.py`)은 저자가 읽는 파일이라
  `vqapr.authoring`에 남겼다(M11에서 `vqapr.public`으로). showcase 파일은 한 바이트도 바뀌지 않았다. digest가 같은
  이유다.
- **테스트 미러.** `tests/extension` · `tests/models` → `tests/component/`, `tests/exchange` →
  `tests/component/exchange/`, `tests/compliance` → `tests/component/compliance/`. 한 단계 깊어진 세 파일은 fixture 경로의
  깊이를 고쳤다. 테스트가 써서 적재하는 컴포넌트 소스 14곳은 사용자의 파일처럼 `vqapr.public`에서 import한다.
  모듈 경로를 문자열로 적은 검사(`test_internal_holds_no_extension_authority`, `test_the_facade_is_not_reached_up_to`,
  `test_capability_absence`, `test_hot_path_costs`)도 새 경로로 옮겼다.

M5b는 여기서 하지 않은 둘이다. `ComponentKind`를 `Role`로 접고, 모든 call의 공통 base를 둔다.

## 트레이드오프

`component/`에는 모듈이 스물둘이다(하위 패키지 셋, `__init__` 넷 제외). 한 역할의 계약 · 결과 · 출하 구현이 한 하위 폴더에 모이는 대신,
문(`reference` · `fingerprint` · `loading` · `conformance` · `scaffold`)이 역할 모듈과 같은 층에 나란히 있다. 문을 하위
패키지로 한 번 더 묶는 것은 이름 하나를 더 배우게 할 뿐이라 하지 않았다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1792 통과 · 5 skip (211 s) |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
| `tests/boundaries/test_the_layers_hold.py` | `component` 20 · `authoring` 21, 위를 보는 import 없음 (test_all에 포함) |
