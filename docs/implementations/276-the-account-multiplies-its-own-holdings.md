# 276 — 계좌는 자기가 담은 종목을 스스로 곱한다

| | |
|---|---|
| **작성 시각** | 2026-09-12 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M9 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §5 · §8, 오너 결정 D6 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `274`(run), `275`(report) |

---

## 왜 이 변경이 있는가

오너의 질문은 이랬다. "valuation을 따로 두지 않고, account 자체가 자신이 담고 있는 종목을 exchange를 지날 때
update하는 것은 어떤가?" 결정(D6)은 둘로 나누는 것이었다. 어떤 가격으로 매길지 고르는 일은 순수 함수로
`domain/valuation.py`에 남는다. 새 행이 있으면 그 가격, 없으면 이전 가격을 관측 시각과 함께 이월, 둘 다 없으면
뺀다. 곱하는 일은 계좌의 몫이다.

바꾸기 전에는 이 둘이 엇갈려 있었다.

- 상태 없는 `ValuationService.mark(snapshot, prices)`가 스냅숏의 보유를 읽어 곱해 `MarkBatch`를 만들었다.
- `Account.mark(state, marks)`는 받은 batch가 자기 보유와 같은 종목 · 같은 수량인지 다시 확인했다
  (`_require_marks_within`). 곱셈이 밖에서 일어났으니 계좌가 그것을 믿을 수 없었다.
- 가격 고르기(`_marks_from_execution_snapshot`)는 엔진의 VALUE 단계 모듈 안에 있었다.

## 무엇이 어떻게 바뀌었는가

| 무엇 | 어떻게 |
|---|---|
| `AccountSnapshot.value(prices)` | 곱셈은 여기 한 곳이다. 가격이 있는 보유마다 수량 × 가격, 이름 순서. 가격이 없는 보유는 평가에서 빠지고 장부에는 남는다 |
| `Account.mark(state, prices, *, marked_at, observed_at)` | 가격 지도를 받아 자기 보유를 곱한다. 교차 확인 `_require_marks_within`은 이제 구성상 참이라 지웠다 |
| `domain/valuation.py` | `SelectedMark` · `ValuationError`, 그리고 `select_prices`(VALUE 단계에서 옮김) · `prices_of`(가격 검사, 옛 `ValuationService._prices`). `ValuationService`는 없어졌다 |
| `AccountMark.provenance` | 지웠다. 저장만 되고 아무도 읽지 않았다(`src` · `tests` 어디에도 읽는 곳이 없다) |
| 체결 뒤 VALUE | 그 provenance를 채우려고만 만들던 `ValuationEvidence`를 더 만들지 않는다. 기록되는 증거(`MarkEvidence`)는 그대로다 |
| 보유만 평가하는 VALUE | 계좌가 곱한 뒤의 marks로 같은 `ValuationEvidence`를 만든다. 필드와 값은 바꾸기 전과 같다 |
| `FlowContext.valuation_service`, `strategy_loop(valuation_service=...)` | 지웠다 |

- **기록은 그대로다.** 곱셈 순서(이름 순), 빠지는 조건(수량 0 · 가격 없음), NAV(현금 + 합계)가 같다. showcase
  digest가 81개 모두 같은 것이 그 확인이다.
- **실패 단계.** 가격 검사는 여전히 `DUE_VALUATION_MARK` 경계 안에서, 계좌의 곱셈은 `DUE_ACCOUNT_MARK` 경계 안에서
  일어난다. 곱셈에 넘기는 스냅숏은 이미 검사된 값이다. 옛 서비스가 곱하기 전에 하던 종목 · 수량 검사가 거절할
  수 있던 입력은 스냅숏의 생성자(또는 검사된 fold)가 이미 거절한다.
- 매 시장 시각에 평가한다(D6). 이것은 바뀌지 않았다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1796 통과 · 5 skip (205 s) |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) — 곱셈 · NAV · 증거가 바뀌기 전과 같다는 확인 |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
