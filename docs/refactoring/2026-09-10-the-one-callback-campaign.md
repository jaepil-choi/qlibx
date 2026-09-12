# 한 콜백 캠페인 — 콜백이 읽은 것을 한 번 만들고, 세션은 run의 기간만 읽고, 심장은 초당 한 번 뛴다

0.14.2 시나리오 stepper의 트레이스(`experiments/exp_246_the_scenario_trace_0_14_2/`)를 이야기가 아니라 중복으로
다시 세자(오너 질문 2026-09-10: "불필요한 호출이나 과정은 없었어?") 일곱 후보가 나왔다. 넷은 중복이었고 셋은
아니었다. 기록 `240`이 선언 쪽에 세운 원칙 — 한 사실은 한 번 읽고 나눠 쓴다(`RunFacts`) — 이 루프 안의 콜백에는
아직 없었고, 기록 `238`이 한 번으로 줄인 시각 열 읽기는 그 한 번이 표 전체였다.

브랜치 `redesign/one-callback`, develop 0.14.2(`a30b6a83`, stepper 커밋 포함) 위에서 시작.

## 후보 일곱 — 넷을 고치고 셋을 물렸다

| 후보 | factor run (10 결정) | stop-loss (37 결정) | 판정 | 기록 |
|---|---|---|---|---|
| `_actual_source_refs` — 콜백마다 stamp와 evidence가 같은 창에서 같은 튜플을 두 번 | 20회 | 71회 | **중복.** decide 뒤 한 번 만들어 둘에 넘긴다 | `246` |
| `strategy.inputs()` — 매 decide마다 선언을 다시 묻는다 | 15회 | 42회 | **중복.** `ComputeHandler`처럼 조립 때 한 번 | `246` |
| `distinct_values` — 10세션 run이 3년 표의 시각 열 전체를 읽고 Python이 자른다 | 735 시각 | 735 시각 | **중복.** run 기간 ± 1일로 묶어 읽는다 | `247` |
| `heartbeat` → `os.utime` — record chunk마다 lock을 만진다 | 110회 | 404회 | **과함.** 기준이 120 s이므로 초당 한 번 | `248` |
| `prepare_model_state` — 시장 시각의 `fill`마다 memory를 다시 프레이밍 | 10회 | 37회 | **중복 아님.** 프레이밍되는 것은 전략이 아니라 거래소(stateful component)의 memory이고, 거래소는 그 시각에 실제로 돌았다(`execute`). 돌지 않은 component는 `None`으로 넘어가 이월된다 | — |
| `verify_roster` — run 시작마다 명단 parquet을 새로 읽는다 | 404 ms | 352 ms | **이득 없음.** 비용의 실체는 lazy `import pyarrow.parquet`(프로세스당 한 번)이고, 명단을 duckdb로 읽어도 그 import는 첫 record chunk(`_arrow_table`)에서 그대로 난다. 매 run 새로 읽는 것 자체는 이슈 009의 설계 | — |
| `fingerprint_component` — run 시작의 `_as_loaded_fingerprints`가 freeze가 방금 해시한 파일을 다시 | 2회 | 2회 | **두었다.** 기록 242의 결정("as-loaded 영수증은 디스크에서 다시 잰다") | — |

## 마일스톤과 기록

| 마일스톤 | 기록 | 무엇이 바뀌었나 | 게이트 |
|---|---|---|---|
| M1 콜백의 사실 하나 | `246` | `CallbackHandler`가 `inputs()`를 한 번 들고, `source_refs`를 decide 뒤 한 번 만들어 `_stamp_intent`·`_callback_evidence`에 넘긴다 | 콜백당 1회 · run당 1회 카운트 테스트 둘, 봉투 baseline 동일 |
| M2 세션은 run의 기간 | `247` | `scan.distinct_values(not_before, not_after)` — `TIMESTAMPTZ` 리터럴(파라미터 바인딩은 첫 호출 +450 ms); `Workspace.evaluation_times(between=)`; `preflight._session_bounds` = `[start − 1d, end + 1d]` | 묶인 읽기 1회 · agenda·horizon 동일 |
| M3 심장은 초당 한 번 | `248` | `LOCK_TOUCH_EVERY = 1.0`, `heartbeat`가 monotonic으로 절제 | 20 chunk → utime 1회 |
| M4 문서·스탬프 | — | 이 요약 · 0.14.3 | test_all · digest 83/83 · release_check |

## 무엇이 달라졌나 (`experiments/exp_246`의 트레이스, 같은 sample door에서 `--force`로 다시 뜸)

| 세는 것 | factor run 전 → 후 | stop-loss run 전 → 후 |
|---|---|---|
| `_actual_source_refs` | 20 → 10 | 71 → 37 |
| `inputs()` | 15 → 6 | 42 → 6 |
| 시각 열에서 읽은 instant | 735 → 11 | 735 → 38 |
| `os.utime` (lock) | 110 → 1/초 | 404 → 1/초 |
| 호출 수 | 27,853 → 25,913 | 68,066 → 63,021 |

ms는 적지 않는다. 뒤의 트레이스는 fast 테스트가 도는 기계에서 떴고, 프로파일러 아래의 ms는 판끼리 비교할 값이 아니다
(기록 240의 실측: 3년 run의 `check`는 프로파일러 없이 ~100 ms). 계산된 숫자는 하나도 다르지 않다: 체결 · 계좌 ·
비중 dataset이 0.14.2와 같고(showcase digest 83/83), sample door의 `check`·`run` 봉투 8개가 바이트 단위로 같다.

## 결정 로그

- **경계는 리터럴로.** duckdb에 tz-aware datetime을 파라미터로 바인딩하는 첫 문장이 프로세스당 ~450 ms를 낸다
  (125만 행: 파라미터 590 ms · 리터럴 80 ms · 전체 열 107 ms). ISO 문자열은 숫자와 구분자뿐이라 리터럴이 안전하다.
- **하루의 여유.** agenda는 venue-local 날짜로, horizon은 instant로 자른다. 시간대가 무엇이든 그 날짜의 instant는
  `[start − 1일, end + 1일]` 안에 있고, 자르기 자체는 손대지 않았으므로 답이 같다.
- **거래소의 memory는 그 시각에 프레이밍한다.** 후보 다섯째를 물린 이유: `_component_states`는 "돌지 않은 component는
  `None`으로 이월"을 이미 지키고 있고, `fill`에서 돌아간 것은 거래소다.
- **pyarrow는 프로세스의 고정 비용이다.** 명단 읽기를 바꿔도 import는 첫 record chunk로 옮겨갈 뿐이다. run 경로에서
  pyarrow를 빼는 것(record writer · cube의 arrow 표)은 별개의, 더 큰 캠페인이다.

## 범위 밖으로 남긴 것

- run 경로의 pyarrow import(프로세스당 ~350–400 ms; `--jobs 16`이면 worker마다).
- 검증·시작 단계의 `inputs()` 다섯 번(`load` ×2 · 판정 · freeze · run 시작) — 각각 다른 물음이지만, `RunFacts`가
  요구 목록도 들면 하나가 된다.
- `--jobs` worker가 run마다 `verify_run`을 다시 도는 것(기록 240이 남긴 것 그대로).
