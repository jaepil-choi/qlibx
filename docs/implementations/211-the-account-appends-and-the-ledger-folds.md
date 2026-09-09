# 211 — The account appends, and the ledger folds

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M11 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` Stage 4 시작) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §5.1 (통장은 append-only 원장) · §5.2 (원장 항목은 한 모양) · §5.3 (Fill-only가 안 되는 이유) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `210` (The venue is handed a dictionary and keeps its own settings) |

---

## 왜 이 변경이 있는가

`AccountState`는 원장이 아니었다. `snapshot`이 진실이고 `fill_history: tuple[object, ...]`는 발행
뒤 버려지며 `mark_history`는 `retained_marks`만큼만 남는다 — 설계 §5.1의 진단 그대로, *"원장의
캐시된 fold + 발행 대기 버퍼"*. 그 어긋남이 낳은 것 셋: `_appends_one_mark`가 retention을 감안해
tail을 비교했고, `AccountState.__post_init__`이 전이마다 이력 전체를 재검증했고, `Prepared*` 세 타입
(`PreparedAccountFill` · `PreparedAccountTransition` · `PreparedAccountValuation`)이 각자 "무엇이 안
변해야 하는가"를 손으로 적었다.

그리고 한 가지 더, 이 마일스톤의 acceptance(AC-12: *"중간에 죽은 run이 유효한 짧은 원장을 남긴다"*)를
쓰다 발견한 것: **죽은 run은 fill을 하나도 안 남기고 있었다.** 아래.

---

## 무엇이 어떻게 바뀌었는가

### `LedgerEntry` — 한 모양 + 출처 태그 (`domain/ledger.py`)

```python
LedgerEntry(at, cash: Decimal, positions: {id: Δqty}, origin: str, detail: {portable})
fill_entries(at, fills: FillBatch) -> tuple[LedgerEntry, ...]     # origin "fill", 체결마다 하나
fold(snapshot, entries) -> AccountSnapshot                        # domain/account_state.py: 버전 +1, 델타 적용
```

`cash`·`positions`는 **델타**다. 둘 다 0일 수 있다 — 거절된 체결은 아무것도 안 바꾸지만 run이 뒤에
보여야 하는 사실이라(`detail.reason`) 항목이다. `detail`은 출처의 것: 체결이면 요청 수량·가격·비용·
카테고리. `vqapr.fill` 테이블은 `origin == "fill"`인 항목에서만 쓴다(§5.3: 배당을 0수량 매수로
인코딩하면 회전율·fill rate가 거짓이 된다 — 그래서 origin이 있다). ACCRUE(M7의 빈 자리)가 다음
origin이 될 곳이다.

### `AccountState` = fold + 창 + 마지막 append

```python
AccountState(snapshot, marks: tuple[AccountMark, ...] = (), ledger: tuple[LedgerEntry, ...] = ())
```

`snapshot`은 지금까지의 fold, `ledger`는 **마지막 append가 만든 항목들**(record로 발행되고 버려진다
— 상주 상태는 run 길이와 무관), `marks`는 소비자가 읽겠다고 선언한 만큼의 창(`Account.retained_marks`,
"원장 밖 메모리 창의 성질"). `__post_init__`이 검사하는 것은 창 길이 안에서 검사할 수 있는 것뿐 —
mark의 버전·시각 순서, 마지막 mark가 이 snapshot을 값매김하는가. `mark_history`/`fill_history`라는
이름은 사라졌다.

### `Account` = append 권한

```python
Account.append(state, entries, *, expected_version) -> PreparedAppend   # 버전 순서 + 결과가 계좌인가
Account.mark(state, marks, *, provenance, marked_at, observed_at) -> PreparedMark  # 보유를 값매김하는가
Account.commit_append(prepared) / commit_mark(prepared)                 # optimistic: state == source
```

두 문. `append`는 "이 항목들을 이 상태 뒤에 붙일 수 있는가"만 묻는다 — `expected_version`이 맞는가,
fold한 결과의 현금이 음수가 아닌가, long-only에 short이 없는가. 체결의 산술(가격×수량=현금)은
`Fill`이 이미 증명했고 여기서 다시 묻지 않는다(§5.2: *"통장이 검사 않는 것: 출처별 불변식"*). `mark`는
체결 뒤든 보유 장부든 **하나의 문**이다 — 둘의 차이는 원장이 직전에 무엇을 했는가지 mark의 관심이
아니다. `prepare_fill`/`prepare_mark`/`prepare_valuation`/`commit_fill`/`commit_valuation`,
`JournalEntry`, `Prepared*` 셋, `_appends_one_mark` 전부 사라졌다.

`PreparedAppend`·`PreparedMark`의 `__post_init__`은 각각 한 문장짜리 불변식이다: append는 버전을 딱
하나 올리고 항목을 실어 나르며 mark를 바꾸지 않는다; mark는 snapshot도 ledger도 바꾸지 않고 마지막
mark가 자신이다.

### 흐름

`execution.fill`: `fill_entries(target_at, fills)` → `account.append(...)` → `state.prepare_account_commit(account=prepared)`
(`fill=` 인자 삭제; fill 행은 `_fill_rows(entries, version)`이 `LedgerEntry.detail`에서 쓴다) →
`commit_append`. `valuation.mark_fill`/`mark_held`: 둘 다 `account.mark(state, ...)` → `commit_mark`.
`run_state.prepare_marked`/`prepare_valuation_only`는 `PreparedMark`를 받는다(둘을 한 갈래로 접는 것은
M12).

### 발견해 고친 것 — 죽은 run은 fill 테이블을 남기지 않았다

AC-12 테스트(`tests/flow/test_a_dead_run_leaves_a_valid_ledger.py`: 셋째 결정에서 죽는 전략, store
있음)가 처음에 `vqapr.fill` 행 0개로 실패했다. record 디렉터리에 `vqapr.account`·`vqapr.weight`는
있고 `vqapr.fill`이 없었다. `prepare_account_commit`이 fill 행을 root의 chunk에 직접 넣고
`new_rows`로 sink에 흘리지 않아, fill은 **`freeze_strategy_record`가 끝에서 root의 잔여 행을 쓸 때만**
디스크에 닿았다 — 완주한 run에서는 보이지 않고 죽은 run에서만 보이는 결함. 다른 테이블처럼
`_stage_rows`를 지나게 했다. 이제 죽은 run의 디스크는 §5.1이 말한 "짧은 이야기"다: 테스트가 fill
행을 버전별로 fold해 마지막 `vqapr.account` 행의 현금과 일치함을 본다.

### 잃은 것

- `Account.prepare_fill(state, fills, expected_version)` — 호출자가 `fill_entries(at, fills)`를
  먼저 만든다. 테스트 6곳.
- `AccountState.fill_history`의 `JournalEntry.fill`(`Fill` 객체) — `ledger[i].detail`의 portable
  값으로. `test_time_002`의 단언 하나가 `entry.fill.dealt_quantity`에서 `entry.positions["A"]`로.
- `PreparedAccountTransition`이 fill과 mark를 한 값에 묶어 주던 것 — 이제 `Filled.committed_root.account`
  (append된 상태)에 mark를 붙인다. 묶음이 필요 없어진 것이지 잃은 것이 아니다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1654 passed (213s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      83/83 — 재기록 없이
```

기준선 회귀(둘째 척추 변경): **record가 한 바이트도 안 움직였다.** fill 테이블은 같은 행을 같은 순서로 — 원장이 발행되는 시점만 끝에서 commit마다로 앞당겨졌고, 완주한 run의 결과는 동일하다. `strategy.json`의 account 블록은 원장 fold라 같다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`domain/ledger.py`는 `account_state`를 import하지 않는다.** `fold`는 snapshot 옆(`account_state.py`)에
  산다. 처음엔 `ledger`가 `AccountSnapshot`을 import하고 `account_state`가 `LedgerEntry`를 지연
  import했는데, deferred-import 상한(10)이 바로 잡았다. 순환은 지연이 아니라 배치로 푼다.
- **ruff `--fix`가 `# noqa` 주석을 지우면 그 줄을 겨눈 문자열 치환이 빗나간다.** 치환은 count를
  단언한다(이번엔 안 해서 한 턴을 먹었다).
- **"완주한 run에서 테이블이 있다"는 "스트리밍된다"의 증거가 아니다.** 끝에서 root 잔여 행을 쓰는
  경로가 가려 준다. 죽는 run으로만 보인다 — AC-12가 그 테스트다.

---

## 다음 기록이 이어받을 것

- **M12.** `PreparedRunState`로 가는 세 갈래(`prepare_account_commit`·`prepare_marked`·
  `prepare_valuation_only`)를 한 갈래로; `flow/freeze.py`의 엔진 값 → record 번역 축소. 실제 감소량을
  Progress에 적는다.
- `Filled.prepared_fill`은 `PreparedAppend`다. M12가 `Prepared*`를 합치면 이름이 바뀔 수 있다.
