# 207 — One instant, one order

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M7 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 2c·2d) — **Stage 2 완료** |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3.1 (한 시각의 순서) · §7.3 (Accrual — 자리만) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `206` (시장 시계는 이벤트 소스다) |

---

## 왜 이 변경이 있는가

M6이 시장 시계를 루프에 넣었지만 한 시각에서 일어나는 일은 아직 두 갈래였다: pending이 그 시각을
가리키면 `execute_due`(그 안에 체결 → 평가 → 모니터링 → 피드백이 한 함수로), 아니면 `value_at`(평가 →
모니터링). 같은 단계 VALUATION·COMPLIANCE가 두 함수에 두 벌로 있었고, 설계 §3.1의 순서

```
1. ACCRUE  2. EXECUTE  3. VALUATION  4. COMPLIANCE  5. DECIDE
```

는 코드 어디에도 **한 줄로** 적혀 있지 않았다. ACCRUE는 자리조차 없었다.

---

## 무엇이 어떻게 바뀌었는가

### `_handle_market`이 순서표다

```python
self._accrual.accrue(instant)                                   # 1. ACCRUE      (빈 자리)
filled = None if due is None else self._execution.fill(due)     # 2. EXECUTE     (pending 이 이 시각이면)
marked = mark_held(instant) if filled is None else mark_fill(filled)   # 3. VALUATION
monitoring = self._valuation.monitor_at(instant, occurrence=…)  # 4. COMPLIANCE
result = HeldResult(…) if filled is None else self._execution.close(filled, marked, monitoring)
```

DECIDE는 같은 시각의 별개 이벤트이고 정렬 키가 뒤에 둔다(M6). 다섯 줄이 설계의 다섯 줄이다.

### `execute_due`가 둘로 갈라졌다

`ExecutionHandler.fill(pending) -> Filled`가 EXECUTE다 — 스냅샷, 종목 게이트, 주문 계획, venue,
`prepare_fill`, commit evidence, account commit, publish. 돌려주는 `Filled`는 다음 단계들이 읽을 것
전부(스냅샷·체결·prepared fill·직전 mark·commit evidence·commit root)다. `close(filled, marked,
monitoring) -> DueExecutionResult`는 체결의 에필로그 — feedback evidence와 그 발행. 옛 함수의 가운데
토막(mark 선택 → mark → `prepare_mark` → `prepare_marked` → `commit_mark` → `publish_marked`)은
`ValuationHandler.mark_fill(filled) -> Marked`로 옮겨 갔고, M6의 `value_at`은 모니터링을 떼고
`mark_held(instant) -> Marked`가 됐다. `Marked`는 root·mark·evidence·selected marks다.

lifecycle 순서는 글자까지 그대로다: ACCEPTED_INTENT → ACCOUNT_COMMITTED → MARKED → (MONITORED) →
FEEDBACK_PUBLISHED. 피드백 발행이 모니터링 **뒤**인 것도 그대로 — 설계는 COMPLIANCE와 DECIDE 사이의
순서만 자유라고 했고, 피드백은 EXECUTE의 증거 마감이라 순서에 영향이 없다.

### ACCRUE의 자리

`flow/strategy/accrual.py`의 `AccrualHandler.accrue(instant)`. 아무것도 하지 않는다 — 설계 §7.3:
*"배당·대차거래 수익·funding·선물 일일정산·펀드 설정/환매가 갈 자리다. MVP 범위 밖이며 자리와
배선만 확정한다."* 그래도 `SimulationStage.MARKET_ACCRUE`(`simulation.market.accrue`)로 guard되고
timing에 잡힌다 — 언젠가 비용이 생길 때 record에 그 열이 이미 있다.

### 순서를 지키는 테스트

`tests/boundaries/test_a_market_instant_keeps_the_stage_order.py` (AC-8) 둘:

- **코드의 순서.** `_handle_market`의 소스에서 `.accrue(` → `.fill(` → `.mark_` → `.monitor_at(` →
  `.close(`가 이 순서로 나타난다 — 재배열이 눈에 보이는 diff가 되도록 텍스트로 잡는다. 그리고
  `MarketEvent`의 정렬 키가 같은 시각 occurrence보다 앞이다.
- **실행의 순서.** 1분 테이블 위 `every: 1m` 전략(AC-1 harness)을 in-process로 돌려, 09:01에서
  trace가 `[DueExecutionTrace, OccurrenceTrace]`이고 lifecycle이 `MARKED(09:00 빈 장부) →
  ACCEPTED_INTENT(09:00) → ACCOUNT_COMMITTED → MARKED → FEEDBACK_PUBLISHED → ACCEPTED_INTENT(09:01)`
  임을 본다: 먼저 정산하고 평가한 뒤에 결정한다.

---

## 무엇을 잃었나

- `ExecutionHandler.execute_due`, `ValuationHandler.value_at`. `ExecutionHandler`는 더 이상
  `ValuationHandler`를 받지 않는다 — 두 handler는 서로를 모르고 루프가 순서를 안다.
- `test_time_002`의 두 monkeypatch가 `execution._marks_from_execution_snapshot`을 겨눴다 —
  mark가 valuation으로 갔으니 `valuation._marks_from_execution_snapshot`으로.
- stage 이름은 **안 바꿨다.** `DUE_*`는 옛말이지만 실패 코드(`strategy.due.*`)와 timing 키에 박혀
  있고, 이름을 바꾸는 것은 순서를 고정하는 것과 다른 결정이다. `MARKET_ACCRUE` 하나만 새 이름 체계로
  들어갔다 — 다음에 바꿀 때 그쪽으로 맞춘다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1643 passed (+ 새 boundary 2, 따로 실행)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      81/81 — 재기록 없이
```

**record가 한 바이트도 안 움직였다.** 함수 경계가 옮겨 갔을 뿐 전이·evidence·행은 같다 — `MARKET_ACCRUE`가
timing에 키 하나를 더하지만 digest는 timing을 떨군다. 첫 스위트에서 떨어진 것은 둘, 둘 다
`test_time_002`가 `execution._marks_from_execution_snapshot`을 monkeypatch하던 것 — mark가 valuation으로
갔으니 그쪽을 겨누게 바꿨다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`Filled`가 `previous_mark`를 들고 가야 한다.** 옛 `execute_due`는 `account_state.latest_mark`를
  commit **전에** 읽어 mark 선택의 `previous=`로 썼다. commit 뒤 root에서 다시 읽으면 같은 값이지만
  "commit 전 상태"라는 뜻이 흐려진다. `Filled.previous_mark`로 그 시점을 고정했다.
- **한 파일을 통째로 다시 쓸 때 Write는 `Read` 후에만 된다.** 스크립트로 고친 파일은 도구가 "바뀌었다"고
  보므로 한 줄이라도 먼저 읽는다. 사소하지만 한 턴을 먹는다.
- **부분 적용된 스크립트는 되돌리고 다시 돌리지 말고, 남은 것만 돌린다.** M6에선 되돌렸고(3개 파일),
  여기선 적용된 앵커를 빼고 나머지만 담은 둘째 스크립트를 만들었다. 둘 다 되지만 둘째가 싸다.

---

## 다음 기록이 이어받을 것

- **Stage 2가 끝났다.** 척추가 설계 §3·§3.1이다: 시계 둘, 한 시각의 다섯 단계, ACCRUE 자리.
- **Stage 3 (M8–M10).** `Constraint` 확장점 제거(→ 순수 함수 kit), `Compliance` 신설(시장 시계의
  COMPLIANCE 단계가 지금은 `monitor_at`이 `constraints`를 돌리는 것 — 그것이 Compliance가 될 자리),
  `Exchange` 계약 좁힘 + 종목 사전.
- `monitor_at(cutoff, occurrence=)`의 `occurrence`는 evidence를 위한 것뿐이다. Compliance가 독립
  관찰자가 되면(§7.2) 그 인자는 사라진다.
