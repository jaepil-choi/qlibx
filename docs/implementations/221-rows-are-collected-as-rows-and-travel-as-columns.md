# 221 — Rows are collected as rows and travel as columns

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 P1 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **측정** | `experiments/exp_221_the_market_clock_cost/` |
| **브랜치** | `redesign/one-loop` |

---

## 왜 이 변경이 있는가

두 시계 캠페인 뒤로 시장 시계의 모든 점에서 장부가 평가되고, 평가마다 `vqapr.account`에 보유
종목 수만큼 행이 쓰인다. 3,000 종목 · 1분 execution table · 하루면 120만 행이고, 그 행 하나가
recorder에서 디스크까지 가는 길에 **다섯 번** Python을 지났다:

```text
valuation.measurement_recorder   dict 하나 만들고
InvocationRecorder.append        normalize_rows: 필드 이름마다 공백 검사, 셀마다 normalize_scalar, 봉투 붙인 dict 또 하나
staged_rows                      dict(row) 복사
run_state._stage_rows            MappingProxyType(row) 감싸기
writer.append → _arrow_table     row.get(column) 로 열 재조립, 셀마다 isinstance 로 타입 재추론
```

3,000 종목 하루 117초 중 63초가 이 길이었다(exp_221 기준선). 그중 42초는 **`TableSpec`이
선언 시점에 이미 검증한 필드 이름을 행마다 다시 검사**하는 것이었다 — 7,400만 번의 문자 검사.

## 무엇이 어떻게 바뀌었는가

**행은 행으로 모으고, 열로 이동한다.**

- `domain/shapes.py` — `RecordChunk(table_id, columns)`: 한 발행의 한 테이블, 열 튜플들. 검증하지
  않는다(스테이징한 곳이 했다). `rows()`가 메모리 안 독자를 위한 행 뷰, `from_rows`가 행
  모양의 문. `normalize_column`: `normalize_scalar`의 규칙을 **열의 distinct 타입** 위에서
  한 번 적용하고, 셀마다 규칙이 있는 타입(float·Decimal 유한, datetime aware)만 그 셀들을 다시
  본다.
- `authoring/records.py` — recorder가 처음부터 열(필드당 list)로 스테이징한다. `append_batch`는
  행의 키 집합을 `TableSpec.field_set`과 한 번 비교하고 셀만 본다(저자 행은 여전히 셀마다
  검증). 새 `append_columns`는 프레임워크 테이블의 문 — 열째로 받아 `normalize_column`으로
  검사한다. `staged_chunks()`가 봉투 열(run_id·producer_id·stage·event_time 상수, sequence
  range)을 붙인 `RecordChunk`들을 낸다. `staged_rows()`는 그 위의 행 뷰로 남는다.
- `flow/engine/run_state.py` — root의 `_recorder_chunks`가 `RecordChunk`를 담고, `recorder_rows`가
  그것을 읽기 전용 행으로 되돌리는 유일한 자리. `row_sink(table_id, rows)` → `sink(chunk)`.
  `PreparedRunState.new_rows` → `new_chunks`. 체결 행은 `RecordChunk.from_rows`.
  **`recorder_manifests`를 지웠다** — `run_state.py` 밖에서 읽는 곳이 없었고 발행마다 tuple을
  이어 붙여 발행 수에 이차였다. `InvocationRecorder.manifests()`는 공개 표면이라 남는다.
- `record/schema.py` — `_arrow_table`이 열을 받는다. `_arrow_type`은 `{type(v) for v in values}`
  한 번(C에서 돈다)으로 distinct 타입을 찾고 그 몇 개만 분류한다. "한 열에 두 종류" 거부는
  그대로다.
- `record/writer.py` — `append_chunk(chunk)`가 sink. `append(table_id, rows)`는 행 모양의 문으로
  남아 `from_rows`를 거친다(freeze의 fallback, 테스트).
- `flow/run/valuation.py` — `measurement_recorder`가 `_ACCOUNT` 행과 보유 행을 열 일곱 개로
  한 번에 `append_columns`.

record의 디스크 모양은 바뀌지 않았다. 열 이름·타입·`sequence`·봉투 전부 같다.

## 측정 — exp_221, 3,000 종목 × 1일 (시장 시계 390점)

| | 이전 | P1 뒤 |
|---|---|---|
| run | **117.4 s** | **62.3 s** |
| `account_mark` (행 쓰기) | 68.4 s | 9.5 s |
| `snapshot` | 17.4 s | 19.6 s (P3의 몫) |
| `compliance` | 14.5 s | 15.9 s (P4의 몫) |

행 경로 63초가 약 10초로. 남은 세 항목은 P3·P4가 잰다.

## 가드 — `tests/flow/test_hot_path_costs.py`

- `append_columns`는 `normalize_scalar`를 **0번** 부르고, `append_batch`는 셀마다 부른다.
- 열 검사는 셀 검사가 거부하던 것을 거부한다(NaN · naive datetime · 비이식 타입 · 길이 불일치 · 미선언 필드).
- writer는 chunk의 `rows()`를 부르지 않는다(monkeypatch로 raise).

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1641 passed, 5 skipped
showcase digest                         81/81 (show_003은 손으로 도는 showcase)
```

**digest 게이트를 checkout 독립적으로 만들었다.** run identity는 소스 경로를 접어 넣은 해시라
같은 선언을 worktree에서 돌리면 `run_id` 열만 다른 record가 나오고, 기준선은 그것을 통째로
비교했다. `scripts/showcase_record_digest.py`가 64자리 hex를 마스킹하고 `--showcases PATH`로
다른 checkout을 digest할 수 있게 했고, 기준선을 develop `9ce50725`의 산출물로 다시 썼다(기록
215가 run identity를 바꾼 뒤로 낡아 있었다). 표는 이제 두 checkout에서 글자까지 같다.

## 남긴 흔적

- **`recorder_rows`의 키 집합은 그대로다.** recorder가 선언한 모든 테이블에 대해 빈 chunk도
  스테이징하므로, sink 없는 run의 `recorder_rows`에 빈 테이블이 `()`로 보이던 것이 유지된다.
  `test_acceptance`·`test_monitoring_findings_reach_the_record`가 그것을 본다.
- **writer의 `event_time` 집계는 distinct 집합 위에서 한다.** recorder chunk의 `event_time`은
  모든 행이 같으므로 행마다 `str(at)`를 하던 것이 한 번이 된다. 열이 없는 chunk(테스트가 행
  모양으로 넣는 것)는 전처럼 `"None"` 하나로 센다.
- bash heredoc 안의 `\"\"\"`가 두 번 파서를 깼다. 긴 패치는 파일로 쓴 뒤 실행한다.
