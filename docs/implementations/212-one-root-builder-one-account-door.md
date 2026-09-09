# 212 — One root builder, one account door

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M12 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`) — **Stage 4 완료** |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §5.1 (`Prepared*` 세 타입이 각자 "무엇이 안 변해야 하는가"를 손으로 쓴다) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `211` (The account appends, and the ledger folds) |

---

## 왜 이 변경이 있는가

M11이 `Account` 쪽의 `Prepared*` 셋을 `PreparedAppend`·`PreparedMark` 둘로 접었지만,
`flow/engine/run_state.py`는 여전히 세 갈래였다 — `prepare_account_commit`(append),
`prepare_marked`(체결 뒤 mark), `prepare_valuation_only`(보유 장부 mark). 뒤의 둘은 M11 이후 같은
`PreparedMark`를 받아 같은 일을 하면서 pending 처리만 달랐고, 그 차이도 append가 이미 pending을 소비한
뒤라 사실상 없었다. 그리고 일곱 `prepare_*` 전부가 `AcceptedRunState`의 **열네 필드를 매번 손으로
베껴 쓰고 있었다** — 전이가 바꾸는 것이 실어 나르는 것에 묻혀 있었다. `publish_*` 래퍼 다섯은 한 줄짜리
`_publish_infallible` 호출이었다.

---

## 무엇이 어떻게 바뀌었는가

### `_advance(root, **changes)` — 다음 루트

전이는 자기가 **바꾸는 것만** 이름 짓는다. `lifecycle` · `states/payloads/verified` · `current_model_state_ref`
· `component_refs` · `account` · `pending` · `chunks/manifests` · `feedback` · `finalization` · `commits`.
안 넘긴 필드는 root의 것 그대로. 일곱 전이가 이 하나로 쓴다.

### `prepare_account(account: PreparedAppend | PreparedMark, *, evidence, pending_id, envelope, recorder, component_memory)`

한 문. 공통: `root.account == account.source`, component memory 커밋, recorder 행 스테이징.
`PreparedAppend`면 `pending_id`가 root의 pending과 같아야 하고 그것을 소비하며(`pending=None`), fill 행을
`_stage_rows`로 흘리고, lifecycle은 `ACCOUNT_COMMITTED`. `PreparedMark`면 pending을 건드리지 않고
lifecycle은 `MARKED`. 옛 `prepare_marked`의 `mark=` 인자(PreparedMark가 이미 나르는 것을 다시 받아
비교하던 것)는 사라졌다.

### `publish_infallible`

`publish_account_commit` · `publish_marked` · `publish_valuation_only` · `publish_monitoring` ·
`publish_feedback` → 하나. `publish`(callback hook 있음)는 그대로.

### 호출자

`execution.fill`: `prepare_account(prepared_fill, pending_id=..., evidence=..., envelope=..., component_memory=...)`;
`valuation.mark_fill`/`mark_held`: `prepare_account(prepared_account, evidence=..., recorder=...)`;
feedback·monitoring: `publish_infallible(...)`.

### `freeze.py` — 예측이 빗나갔다

ExecPlan은 "엔진 값 → record 번역 중 사라지는 부분을 지운다"고 했다. 읽어 보니 사라지는 값이 없었다:
`freeze_strategy_record`가 접는 것은 전부 record 필드로 나오고, `contract_report`의 duck-typed 읽기
(`getattr(trace, "result", None)`)는 `tests/compliance/test_a_residue_within_tolerance_is_not_a_breach.py`가
`SimpleNamespace`로 기대는 문이다. **freeze.py는 0줄 줄었다.** 감소는 전부 run_state에서 났다.

### 감소량 (측정)

| 파일 | M10 끝 | M12 끝 | Δ |
|---|---|---|---|
| `flow/engine/run_state.py` | 731 | 632 | −99 |
| `account/account.py` | 356 | 252 | −104 (M11) |
| `domain/account_state.py` + `domain/ledger.py` | 172 | 209 + 113 = 322 | +150 (M11, `LedgerEntry`·`fold` 신설) |
| `flow/freeze.py` | 371 | 371 | 0 |

타입: `PreparedAccountFill`·`PreparedAccountTransition`·`PreparedAccountValuation`·`JournalEntry` 넷 →
`PreparedAppend`·`PreparedMark`·`LedgerEntry` 셋(M11). run_state의 문: `prepare_*` 7 → 6(계좌 3 → 1),
`publish_*` 6 → 2.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1654 passed (204s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      83/83 — 재기록 없이
```

기준선 회귀(Stage 4 = 둘째 척추 변경의 마무리): **record가 한 바이트도 안 움직였다.** 전이의 모양이 바뀌었을 뿐 루트가 나르는 것과 발행되는 행은 같다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`_UNSET` 센티널로 "안 바꿈"과 "None으로 바꿈"을 가른다.** `pending=None`은 소비, `pending=_UNSET`은
  그대로. `account`·`finalization`도 같다. 타입 체커는 `object`로 받아 `# type: ignore`가 셋 붙는다 —
  오버로드보다 싸다.
- **한 갈래로 접을 때 "차이"가 진짜인지 먼저 본다.** `prepare_marked`(pending None)와
  `prepare_valuation_only`(pending 유지)의 차이는 append가 이미 pending을 비운 뒤라 관찰 불가였다.
  lifecycle 순서 테스트(AC-8)가 그것을 보증한다.
- **예측이 빗나가면 그대로 적는다.** freeze 축소 0줄.

---

## 다음 기록이 이어받을 것

- **Stage 5 (M13–M14).** 배선표 코드화 + 부품/도구 타입(§4.2-4.3), 패키지 재배치 +
  `flow/datamodel`·`flow/strategy` 통합(§10.1 이름은 M14에서).
