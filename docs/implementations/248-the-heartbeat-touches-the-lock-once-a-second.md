# 248 — The heartbeat touches the run lock once a second, not once per chunk

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 콜백 캠페인 (`docs/refactoring/2026-09-10-the-one-callback-campaign.md`) |
| **이슈** | 없음 — `experiments/exp_246` 트레이스 |
| **설계 근거** | 기록 `087`(lock의 mtime이 heartbeat이고 `LOCK_STALE_AFTER`는 120 s), `221`(record chunk는 열 단위로 sink에 간다) |
| **브랜치** | `redesign/one-callback` |
| **앞선 기록** | `087`, `221` |

---

## 왜 이 변경이 있는가

`RunRecordWriter.heartbeat`는 lock 파일의 mtime을 만져 "이 run은 살아 있다"고 말한다. 죽은 run의 id를 다른 run이
가져가는 기준은 두 분(`LOCK_STALE_AFTER`)인데, 만지기는 record chunk를 붙일 때마다였다: 10 결정 run에 110번,
37 결정 run에 404번(`08_run_factor`, `10_run_stoploss`의 `heartbeat` 호출). 로컬 디스크에선 `os.utime` 하나가
싸지만, 이 프로젝트가 자주 놓이는 네트워크 홈(CIFS)에선 하나하나가 왕복이다 — 0.13.0 stepper의 트레이스가 그
자리를 뜬 곳이다.

## 무엇이 어떻게 바뀌었는가

- `record/schema.py`에 `LOCK_TOUCH_EVERY = 1.0`. 두 분의 기준에 초당 한 번이면 백 번을 남기고 말한다.
- `heartbeat`가 `_Buffer.lock_touched_at`(monotonic)을 보고 그 뒤 `LOCK_TOUCH_EVERY`가 지났을 때만 `os.utime`을
  한다. 첫 호출은 만진다. `progress.json`의 주기(`PROGRESS_EVERY`, 5 s)는 그대로이고 같은 시계를 읽는다.

**바꾸지 않은 것.** `heartbeat` 호출 자리(빈 append · chunk 뒤 · 루프의 매 이벤트)와 "절대 raise하지 않는다"는
약속. staleness 판정(`_lock_claim`, `LOCK_STALE_AFTER`).

## 검증

| 검사 | 결과 |
|---|---|
| `tests/record/test_the_heartbeat_touches_the_lock_once_a_second.py` (신규) | 한 초 안의 chunk 20개 → `utime` 1회; `LOCK_TOUCH_EVERY` 뒤의 chunk → 2회; 같은 초의 빈 heartbeat → 그대로 2회 |
| `tests/cli/test_list_shows_a_strategy_still_being_written.py` · `test_the_run_lock_refusal_states_what_it_knows.py` · `tests/internal/test_the_workspace_mutex.py` · `tests/record/` | 통과 — progress.json · stale 판정 · lock 거절문 그대로 |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
