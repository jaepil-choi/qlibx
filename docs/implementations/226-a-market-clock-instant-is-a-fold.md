# 226 — A market-clock instant is a fold

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 L2 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3.1 (한 시각의 순서) · 기록 `213` (순서는 코드에 글자로) |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `225` (`sequence` is the run's one order) |

---

## 왜 이 변경이 있는가

`StrategyEventLoop._handle_market`은 시장 시계 한 점의 다섯 단계를 **모양이 제각각인 지역 변수
넷**으로 이었다.

```text
self._accrual.accrue(instant)                                   -> None
filled = None if due is None else self._execution.fill(due)     -> Filled | None
marked = mark_held(instant) if filled is None else mark_fill(filled)
monitoring = self._compliance.observe(instant)                  -> MonitoringResult | None
result = HeldResult(...) if filled is None else self._execution.close(filled, marked, monitoring)
```

동사 다섯, 시그니처 다섯, 그리고 "체결이 있었나"의 분기가 루프에 두 번. compliance는 방금 마킹된
장부를 받지 않고 `state.current.account.latest_mark`를 **다시 읽어** 자기 evidence를 재조립했다 — 같은
batch를 두 번째 이름으로 부르는 것이고, 첫 마크 전에는 빈 valuation을 지어내는 fallback까지 있었다.

L3(루프 하나)가 요구하는 것은 handler가 **같은 모양**으로 불리는 것이다. 표가 루프를 구동하게 하지
않기로 했으므로(기록 `213`, 캠페인 문서 §2 "하지 않는 것"), 남는 길은 단계들이 하나의 값을 주고받는
것이다.

## 무엇이 어떻게 바뀌었는가

- `flow/run/context.py` — `MarketInstant(at, due, filled, marked, monitoring, result)`. 한 점이 단계를
  지날 때마다 자기 필드 하나를 얻는 frozen 값. `require_marked()`가 VALUATION 뒤에만 오는 단계의
  전제를 말한다.
- 다섯 단계가 한 모양이 됐다: **`(MarketInstant) -> MarketInstant`.**

  | 단계 | 전 | 후 |
  |---|---|---|
  | ACCRUE | `accrue(instant) -> None` | `accrue(at) -> at` |
  | EXECUTE | `fill(pending) -> Filled` (루프가 `due is None` 분기) | `fill(at) -> at`; `due`가 없으면 그대로 |
  | VALUATION | `mark_held(instant)` / `mark_fill(filled)` (루프가 분기) | `mark(at) -> at`; 둘 중 하나를 스스로 고른다 |
  | COMPLIANCE | `observe(instant) -> MonitoringResult \| None` | `observe(at) -> at`; **`at.marked`를 판정한다** |
  | 닫기 | `close(filled, marked, monitoring)` (루프가 `HeldResult` 분기) | `close(at) -> at`; 보유면 `HeldResult`, 체결이면 feedback 발행 |

- `flow/run/loop.py::_handle_market` — 다섯 줄이 됐다. 순서는 그 다섯 줄이다.

  ```python
  at = MarketInstant(at=instant, due=due)
  at = self._accrual.accrue(at)
  at = self._execution.fill(at)
  at = self._valuation.mark(at)
  at = self._compliance.observe(at)
  at = self._execution.close(at)
  ```

  `pending`을 소비했는지의 검사는 루프에서 `fill` 안으로 갔다 — 그것은 EXECUTE의 후조건이지 루프의
  일이 아니다.
- `compliance.py` — `_committed_marks`와 그 fallback이 사라졌다. 규칙이 판정하는 것은 `at.marked.mark`,
  즉 **이 점에서 VALUATION이 방금 커밋한 그 batch**다. root도 `at.marked.root`.

**표가 루프를 구동하지 않는다.** 튜플에 함수를 담아 `for stage in stages` 하는 것도 하지 않았다:
단계가 다섯이고 순서가 이 파일의 다섯 줄이면 그것이 가장 읽기 쉬운 표다. AC-8과 배선표 테스트가
그 다섯 줄의 소스 순서를 그대로 잡는다(`.mark_` → `._valuation.mark(` 하나만 바꿨다).

## 성능

바뀌지 않아야 하고 바뀌지 않았다. 점마다 `replace()` 다섯 번 — 3,000 종목 하루 390점에 2,000번의
작은 dataclass 복사. exp_221: **34.7 s** (두 번 중 작은 값; L1 뒤 35~39 s).

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1648 passed, 4 skipped
showcase digest                         81/81
```
