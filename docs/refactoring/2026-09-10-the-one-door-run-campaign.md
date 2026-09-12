# 한 문(run) 캠페인 — 검사관과 공증인이 같은 서류를 각자 읽지 않는다

0.13.0 시나리오 stepper의 트레이스(`experiments/exp_238_the_scenario_trace_0_13_0/`)를 이야기가 아니라 구조로
다시 읽자 `vqapr run` 하나가 집행표의 시각 컬럼을 5번, 전략 코드를 4번, 거래소를 3번 읽고 있었다. 원인은 run
선언을 이름에서 값으로 푸는 길이 두 벌이라는 것 — `judgments`(모아서 답한다, `check`를 위해 태어남)와
`preflight`(첫 거절에서 멈추고 얼린다, `run`을 위해 태어남) — 이고, 둘은 사고(`docs/issues/archive/015`)를 막으려
기록 `087`·`168`에서 앞뒤로 이어 붙인 것이었다. 오너 결정(2026-09-10): 데이터에 한 것(기록 `234`, `verify_source`)
처럼 합친다. 설계는 `docs/design/2026-09-10-one-door-for-a-run.md`.

브랜치 `redesign/one-door-run`, develop 0.13.1 + 기록 `238`·`239` 위에서 시작.

## 마일스톤과 기록

| 마일스톤 | 기록 | 무엇이 바뀌었나 | 게이트 |
|---|---|---|---|
| M1 특성화 | — (`f6ef3e52`) | sample door의 `check`·`run` 봉투 8개(정상 · datamodel · 결함 셋 · 없는 가격 · 바뀐 집행표)를 정규화해 baseline으로 고정, 재생성은 opt-in | baseline 재생 후 replay 통과 |
| M2 문 하나 | `240` | `flow/declaration/verify.py::verify_run -> RunVerdict`; `check`의 두 phase · 공개 `preflight_run` · `--jobs` worker 둘이 그것을 지난다; `require_judged` 삭제. worker가 판정을 받게 됨(행동 변화 하나) | baseline 바이트 동일 · fast 1,707 |
| M3·M4 사실 하나 | `241` | `preflight.RunFacts`: agenda · 집행표 · horizon · 컴포넌트 · venue를 명령당 한 번 읽고, 못 읽으면 그 예외를 묻는 모두에게 다시 준다; judge와 freeze가 그것을 읽는다; `_agenda_once` 삭제 | baseline 바이트 동일 · 읽기 횟수 테스트 |
| M5 문서·스탬프 | — | architecture §12 · run-backtest skill · 설계 문서 · 이 요약 · 0.14.0 | test_all · digest 83/83 · release_check |

## 무엇이 달라졌나 (읽기 횟수, `vqapr run sample-factor-run` 한 프로세스)

| 사실 | 0.13.1 | 0.14.0 |
|---|---|---|
| 집행표의 시각 컬럼 (`distinct_values` + `candidate_instants`) | 2 + 3 | 1 + 0 (+ run 시작 뒤 1) |
| 전략 import (판정 · freeze · 초기 상태 증명 · run) | 3 + 1 | 2 + 1 |
| 거래소 import | 2 + 1 | 1 + 1 |
| 바뀐 파일의 sha256 (`check`) | 2 | 1 |
| 콜백당 memory 정규화 / 봉투 해시 | 5 / 2 | 3 / 1 |

## 결정 로그

- **verdict는 예외를 그대로 든다.** `(Diagnosis, FrozenRun)`로 접으면 `run`의 `retry_precondition`과 stage가
  사라지거나 `check`의 항목 모양이 바뀐다. 봉투를 지키는 것이 이 캠페인의 첫 조건이었다.
- **blocked + 거절, 둘 다 싣는다.** 설계 §2는 "사실이 안 풀리면 판정은 skipped"를 제안했지만 오너 결정
  2026-09-04(`tests/cli/test_a_judgment_that_could_not_look_is_not_passed.py`)가 "다른 두 진술"로 정해 두었다.
  뒤집지 않는다. 같은 예외 객체가 판정엔 cause로, freeze엔 거절로 두 번 전달된다.
- **판정과 freeze는 모듈 둘로 남는다.** 보고 방식이 다르다(전부 모으기 / 값 만들고 첫 거절). 합친 것은 읽기다.
- **worker는 판정을 받는다.** 배치 안의 run이 순차 `run`과 다른 답을 내는 것은 015의 재발이다.

## 범위 밖으로 남긴 것

- `RunResources`: freeze가 load한 컴포넌트와 horizon을 run에 넘겨 run 시작 때의 재import·재스캔을 없애기.
  `FrozenRun`은 record에 적히는 값이라 살아 있는 객체를 못 싣는다.
- `--jobs` worker가 run마다 `verify_run`을 다시 도는 것(driver가 판정을 한 번 하면 된다).
- `check` 봉투의 중복 두 곳(`run.output_registered` 두 번; freeze 거절 + `judgment.blocked`) — 오너 결정의 영역.

## 검증

stamped 트리(0.14.0)에서 `test_all` 1,738 passed · showcase digest 83/83 · `release_check` 통과 · ruff clean · pyright 0 errors. 특성화 baseline(sample door 봉투 8개)은 M1부터 M4까지 바이트 단위로 같았다.
