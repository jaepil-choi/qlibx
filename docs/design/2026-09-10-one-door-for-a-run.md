# 한 문으로 run을 잰다 — 검사관과 공증인을 `verify_source`의 모양으로 합친다

**Status: DONE (2026-09-10, 기록 `240`·`241`, 브랜치 `redesign/one-door-run`).** 근거는
`experiments/exp_238_the_scenario_trace_0_13_0/`의 트레이스와 기록 `238`·`239`. 오너 결정: 합친다.

**구현이 §2와 다른 두 곳.** (1) 문은 `(Diagnosis, FrozenRun)`이 아니라 `RunVerdict(failures, blocked, frozen,
refusal)`를 돌려준다 — freeze의 거절은 예외 객체 그대로 실린다. 두 동사가 같은 거절을 다르게 그리고(`check`는
failure 항목, `run`은 자기 stage와 `retry_precondition`을 든 raise) 봉투가 바이트 단위로 같아야 했기 때문이다.
(2) §2의 "의존은 건너뛰기로 말한다"(사실이 풀리지 않으면 판정을 blocked가 아니라 skipped로)는 하지 않았다.
오너 결정 2026-09-04(`tests/cli/test_a_judgment_that_could_not_look_is_not_passed.py`)가 "판정이 답하지 못하고
preflight가 같은 결함을 거절하면 봉투는 둘 다 싣는다 — 다른 두 진술"이라고 이미 정해 두었고, 이 캠페인은 그
결정을 뒤집지 않는다. 사실을 한 번 읽는 것(`RunFacts`)은 그 결정과 무관하게 이뤄졌다: 같은 예외가 판정 쪽엔
blocked의 cause로, freeze 쪽엔 거절로 두 번 전달된다.

## 1. 문제

run 선언 하나를 이름에서 값으로 푸는 길이 **두 벌**이다.

| | `judgments` (`flow/declaration/judgments.py`, 767줄) | `preflight` (`flow/declaration/preflight.py`, 921줄) |
|---|---|---|
| 태어난 이유 | `check`: 틀린 것을 **전부** 한 번에 보고한다 | `run`: 이름을 값으로 풀어 `FrozenRun`으로 봉인한다 |
| 보고 방식 | 판정마다 독립, `(failures, blocked)` 목록 | 첫 거절에서 `VqaprError` |
| 읽는 것 | agenda · 집행표 binding · horizon · 전략 load · requirements · 거래소 load · dataset identity · 명단 | **같은 것 전부** + 초기 계좌 · 초기 memory · 출력 이름 |

둘은 사고(`docs/issues/archive/015`: `check`는 거절한 run을 `run`이 돌렸다)를 막으려고 기록 `087`·`168`에서
**앞뒤로 이어 붙인** 것이다. 이어 붙일 때 문제는 정확성이었고, 둘이 같은 서류를 각자 읽는다는 것은 잡히지
않았다. 결과가 트레이스에 그대로 있다(`08_run_factor`): 집행표의 시각 컬럼 5회, 전략 코드 import 4회, 거래소
3회, digest 2회. 기록 `238`은 그중 둘(시각 · digest)에 `Workspace` 메모를 붙였을 뿐이고, 나머지는 항목마다
메모를 붙이는 식으로는 끝나지 않는다.

데이터 쪽엔 이미 답이 있다. 기록 `234`의 `verify_source(registration, spec) -> (Diagnosis, timing, measured)`:
파일을 **한 번** 열어 스키마 → key → span → 값 → 가격 → digest를 **단계**로 재고, 한 단계 안에서는 실패를
**전부 모으며**, 앞 단계가 깨지면 뒤 단계는 묻지 않고(없는 컬럼에 key를 물을 이유가 없다), 통과하면 **잰 값이
붙은 등록**을 함께 돌려준다. 검사와 측정이 한 함수다. run 선언에 같은 문이 없다.

## 2. 결정 (제안)

```
verify_run(workspace, definition) -> tuple[Diagnosis, FrozenRun | None]
```

- **한 번 읽고 두 가지로 답한다.** `Diagnosis`는 모은 실패 전부(코드는 지금 그대로: `JUDGMENT_CODES`의 열한 개 ·
  `execution.*` · `run.*` · `dataset.*`), `FrozenRun`은 실패가 없을 때만.
- **`check`** 는 `Diagnosis`를 봉투로 그린다(`checked · passed · skipped · blocked · failures` 키 그대로).
- **`run`과 Python 문(`execute`)** 은 `diagnosis.raise_if_failed()` 뒤 `FrozenRun`을 쓴다. 한 함수의 두 호출자이므로
  "check는 통과, run은 거절"은 테스트가 아니라 구조로 막힌다(기록 `087`·`168`의 계약이 함수 하나가 된다).
- **단계**(`verify_source`의 다섯 단계에 대응). 한 단계 안에서는 멈추지 않고 전부 모은다.

| 단계 | 묻는 것 | 읽는 것 |
|---|---|---|
| 1 선언 | universe · period · 명단 선언 · execution authority · 출력 이름(`run.output_registered/stale`) | 등록부만 |
| 2 등록 대조 | dataset 등록 여부 · 필드 · 집행 역할 · 가격 · **identity**(digest 1회) | 등록부 + sha256 |
| 3 컴포넌트 | 전략 · 거래소 · 규칙 **load 1회**, requirements, 초기 memory round-trip, 상장 규칙 | import |
| 4 시각 | `evaluation_times` **1회** → agenda → horizon → 결정마다 target · lookback 덮임 · 첫 결정 | 집행표 스캔 1회 |
| 5 계좌 · venue | mode/venue 충돌, 초기 계좌 | 값만 |

- **의존은 건너뛰기로 말한다.** 2단계에서 dataset이 없으면 3단계의 그 dataset에 대한 필드·lookback 질문은
  `skipped`(이름과 이유)이지 실패도 통과도 아니다 — 지금 `check`가 phase에 하는 것과 `_judge_member_datasets`가
  코드 사이에 하는 gate를 한 규칙으로.
- **답하지 못함은 blocked** (`docs/issues/archive/077` 그대로). 어느 항목이든 예상 밖 예외는 `judgment.blocked`로
  cause를 통째로 들고 `Diagnosis`에 들어간다. 통과로 세지 않는다.
- **읽기는 한 번.** 단계 4의 시각, 단계 2의 digest, 단계 3의 load는 함수 안의 지역값이다. 기록 `238`의
  `Workspace` 메모는 그대로 두되(다른 명령도 쓴다) 이 문 안에서는 필요 없어진다.

## 3. 무엇이 사라지나

`judgments()`의 judge 디스패처와 `_agenda_once` · `require_judged` · `preflight_run`(공개 이름은 `verify_run`의 얇은
wrapper로 남긴다: `frozen = preflight_run(...)`을 쓰는 호출자가 `cli/run.py` · `public.execute` · `orchestration`에
있다) · `cli/check.py`의 phase 루프 중 judgments/preflight 두 phase. 전략 load는 판정 + freeze 4회 → 1회
(run이 돌릴 인스턴스 1회는 별도로 남는다 — `RunResources`는 이 설계의 범위 밖, §5).

## 4. 지켜야 하는 것 (이미 테스트가 못 박고 있다)

- 결함 넷을 한 번에 넷으로 보고한다(`tests/cli/test_check.py::test_four_simultaneous_problems_return_four_failures_in_one_call`).
- blocked는 passed가 아니다(`test_a_blocked_judgment_carries_its_cause_separately`).
- `check`와 `run`은 같은 코드로 거절한다(`test_this_verb_adds_no_second_name_for_a_defect_that_has_one`).
- 한 명령은 등록부를 한 번 열고 같은 스냅샷을 본다(`docs/issues/archive/070`).
- 원천은 명령당 한 번 읽는다(기록 `238`의 테스트 셋).
- 봉투의 키와 코드는 바뀌지 않는다. showcase record digest 83/83.

## 5. 범위 밖 (다음 단계)

- **`RunResources`**: freeze가 이미 load한 컴포넌트와 horizon을 run에 넘겨 run 시작 때의 재유도(전략 import 1회 ·
  `execution_horizon` 스캔 1회)를 없애는 것. `FrozenRun`은 record에 적히는 값이라 살아 있는 객체를 못 싣는다.
- `--jobs` worker가 run마다 다시 `verify_run`을 도는 것(driver가 이미 판정했으므로 한 번이면 된다).

## 6. 위험

- 두 모듈 1,700줄을 한 함수의 단계로 옮기는 동안 코드·메시지·`source.key_path`가 한 글자라도 바뀌면 agent 쪽
  reader가 깨진다. 착수는 **특성화**부터: sample 프로젝트와 testbed 보고의 선언들에 대해 `check`·`run` 봉투를 바이트
  단위로 고정하고, 옮기는 동안 그 고정이 지켜지는지를 본다.
- `verify_source`처럼 "앞 단계가 깨지면 뒤 단계는 묻지 않는다"를 너무 넓게 잡으면 `check`가 보고하던 결함 수가 준다.
  단계 사이의 의존은 §2의 표에 적힌 것만이고, 그 밖의 항목은 서로 독립이다.
