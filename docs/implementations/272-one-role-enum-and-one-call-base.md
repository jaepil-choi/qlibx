# 272 — 역할의 이름은 하나고, 네 Call은 한 base를 갖는다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M5b — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §4.2 · §4.4, 오너 결정 D3 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `271`(확장 지점은 한 패키지다) |

---

## 왜 이 변경이 있는가

record `271`로 역할마다 모듈이 하나씩 생겼다. 그래도 두 가지가 남아 있었다.

- **역할을 부르는 열거가 둘이었다.** `domain/wiring.py::Role`은 배선 표의 다섯 행이고,
  `ComponentKind`는 그중 등록할 수 있는 네 행이었다. 값도 같았다(`"data_model"`, …). 두 열거를 잇는 것은
  `ComponentKind.role` 속성 하나였다. 한 개념에 이름이 둘이면 읽는 사람은 둘이 어디서 다른지 찾아야 한다.
  답은 "ACCRUAL 한 행"뿐이었다.
- **"모든 역할은 Call 하나를 받는다"가 문장으로만 있었다.** 세 Call은 ABC였고 `ExecutionCall`은 dataclass였으며,
  넷의 공통 조상이 없었다(아키텍처 §4.4).

## 무엇이 어떻게 바뀌었는가

| 무엇 | 어떻게 |
|---|---|
| `domain/wiring.py` | `EXTENSION_POINTS = (DATA_MODEL, STRATEGY_MODEL, EXCHANGE, COMPLIANCE)`. 등록할 수 있는 역할은 배선 표의 사실이다 |
| `component/reference.py` | `ComponentKind` 삭제. `ComponentRef.kind`는 `Role`이고, 모델 검증이 `ACCRUAL`을 네 값의 이름과 함께 거절한다. `ComponentRef.of`도 같은 것을 확인한다 |
| 52개 파일 | `ComponentKind` → `Role`. import는 `domain.wiring`에서 |
| `component/base.py` | `Call`: 네 Call의 표지(marker) base. `DataCall` · `StrategyCall` · `ComplianceCall`은 `(Call, ABC)`, `ExecutionCall`은 `(Call)` |
| `vqapr.public` | `ComponentKind` 대신 `Role`, 그리고 `Call` |

- **저장된 값은 그대로다.** workspace.yaml의 `kind:`와 지문의 metadata는 모두 역할의 값 문자열(`"data_model"`,
  …)을 쓴다. `ComponentKind`가 쓰던 값과 같으므로, 이전 workspace도 다시 등록하지 않고 읽히고 지문도 바뀌지 않는다.
  digest가 같은 것이 그 확인이다.
- **`Call`에 멤버가 없는 이유.** 세 ABC는 사건의 시각을 `evaluation_time`이라 부르고, `ExecutionCall`은
  `at`이라 부른다. 목표 설계(§4.4)는 `Call.at` 하나다. 하지만 이것은 저자에게 보이는 이름 변경이라, 루프의 어휘를
  바꾸는 릴리스(M11, `occurrence_id` → `event_id`와 함께)로 미뤘다. 그때까지 `Call`은 표지이고 ABC가 아니다.
  멤버 없는 ABC는 ruff B024가 잡는 모양이기도 하다.
- **`project/store.py`.** run이 이름을 대는 컴포넌트를 확인하는 안쪽 함수의 인자 `role: str`("strategy",
  "compliance rule", …)을 `noun`으로 바꿨다. 타입 `Role`과 같은 이름의 문자열 인자는 헷갈린다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1796 통과 · 5 skip (205 s) — 1792에 새 테스트 다섯, `ComponentKind` 이름 확인 매개변수 하나가 빠졌다 |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) — 저장된 kind 값과 지문이 그대로라는 확인 |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
| 새 테스트 | `test_every_call_is_a_call`(넷), `test_accrual_is_a_place_and_not_a_role_a_component_registers_as`, `test_every_extension_point_is_a_row_and_accrual_is_not_yet_one` |
