# 260 — `Rebalance.of` takes a zero weight as "hold none of this name"

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-rebalance-of-refuses-a-zero-weight-that-rebalance-signed-keeps.md` |
| **설계 근거** | 오너 판정 2026-09-11 — "0을 받는다"(대안: 거절문만 고친다) |
| **브랜치** | `develop` |
| **앞선 기록** | `154`(`Rebalance.signed`, 0을 flat position으로 둔다) |

---

## 왜 이 변경이 있는가

incremental testbed의 haiku run이 KOSPI200 비중에서 0.5%p를 빼고 0에서 멈추는 enhanced index를 만들었다. 0은 정당한 목표
("이 종목은 하나도 들지 않는다")인데 `Rebalance.of(long={..., "A000100": 0})`가 run 한가운데서 `long['A000100'] must be
positive: a side is chosen by which mapping ...`로 멈췄다. 같은 0을 `Rebalance.signed`는 flat position으로 받는다 — 두
생성자가 같은 입력에 다른 뜻을 줬고, 거절문은 다른 질문(쪽을 어떻게 고르나)에 답했다. opus run은 0인 종목을 스스로
걸러내고 그것을 "내가 내려야 했던 결정"으로 적었다.

## 무엇이 어떻게 바뀌었는가

`authoring/result.py`:

- `_relative_side`가 음수만 거절한다(`must not be negative: a side is chosen by which mapping ... (a zero holds none of it)`).
  0은 받는다.
- `of`가 크기를 **0이 아닌** 이름으로 정한다(`live_longs`/`live_shorts`): 한 쪽의 정규화 합, 두 쪽인지(= `invested`를
  반씩 나눌지), signed budget인지 모두 그것으로 판정한다. 0인 이름은 비중 0으로 책에 남아 다음 체결에서 들고 있던 것이
  전부 팔린다. 0만으로 된 쪽은 쪽이 아니다 — `long={"A": 1}, short={"B": 0}`는 long-only, A가 1.
- 전부 0이면 `signed`와 같은 문장으로 거절한다("at least one non-zero weight").
- docstring 둘이 이것을 말한다.

## 바꾸지 않은 것

음수 거절(쪽은 매핑이 정한다는 규칙), 한 이름이 두 쪽에 있으면 거절, `invested`의 범위, `rescale`의 정산. 0 없는 입력의
결과는 한 자리도 바뀌지 않는다.

## 트레이드오프

오타로 들어간 0도 조용히 "전량 매도"가 된다. 오너가 그것을 알고 골랐다 — 0 아래로 자르는 틸트가 흔하고, 매번 걸러내는
코드를 에이전트에게 쓰게 하는 비용이 더 크다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/models/test_a_zero_weight_holds_none.py` (신규, 다섯) | 0이 flat으로 남는다; `of`와 `signed`가 0에서 같은 비중; 0만인 쪽은 쪽이 아니다(long-only, 절반으로 나누지 않음); 전부 0은 거절; 음수는 여전히 쪽 규칙으로 거절 |
| `tests/extension/test_authoring_contract.py` | 음수 거절 문구 `must be positive` → `must not be negative` 한 줄 |
| `tests/models`, `tests/exchange`, `tests/flow`, `tests/report` (`-m ""`) | 통과 |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`, records `260`–`263` together) | 1788 passed, 1 skipped, 251.6 s |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
