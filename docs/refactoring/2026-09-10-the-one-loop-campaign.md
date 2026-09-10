# 한 루프 캠페인 — 시장 시계 한 점의 비용을 줄이고, 루프를 하나로

두 시계 캠페인(records `201`-`214`)이 시장 시계를 1급 이벤트 소스로 세웠고, 마지막 두 기록이
빚을 명시적으로 남겼다.

- **기록 214**: *"루프 클래스를 하나로 만들지 않았다. `StrategyEventLoop`는 `RunStateRepository`+
  `FlowContext` 위에, `DataModelEventLoop`는 `RunOutput` 위에 서 있고, 접으려면 척추 변경이다."*
- **기록 213**: *"표를 소비하는 코드는 아직 테스트뿐이다. 표가 루프를 구동하게 하는 것은 하지
  않았다."*

이 캠페인은 그 빚을 갚되, **먼저 그 루프가 얼마나 비싼지 재고 그것부터 줄인다.** 시장 시계가
분 단위가 되면서 루프의 한 점이 하루 390번 돌고, 그 한 점의 비용이 종목 수에 비례하기 때문이다.

## 0. 소유자 결정 (2026-09-10)

1. **분봉도 목표다.** 일봉은 blazing fast, 분봉도 충분히 빨라야 한다. 3,000 종목이 기준이다.
2. **성능을 나쁘게 하지 않는 선에서** clean architecture · maintainability가 의미를 갖는다.
   OOP를 위한 OOP는 과설계다.
3. **사용자 코드를 깨는 것은 상관없다.** `Compliance.observe`의 시그니처가 바뀐다.
4. **P1부터 순서대로 진행한다.** 성능 묶음(P)이 먼저, 루프 묶음(L)이 그 위에서.
5. 브랜치 `redesign/one-loop`, worktree `.claude/worktrees/redesign-one-loop`. **최신 develop에서
   시작한다** — develop `9ce50725`(records 215-220)로 fast-forward 한 뒤 착수.

참고 브랜치 `redesign/four-kinds-and-the-journal`(worktree `redesign-four-kinds`, base
`853957e7`)은 두 시계 **이전**에 갈라져 있어 루프 코드 자체는 참고가 아니다. 가져오는 것은 기록
`203`(역할은 Call 하나를 받는다) · `205`(run 전체 `sequence`) · `207`(`_next(**delta)`) 과
`tests/boundaries/test_a_role_has_one_call.py`, 그리고 exp_205의 "척추를 건드리기 전에 잰다".

## 1. 측정 — 어디에서 시간과 메모리가 나가는가

`experiments/exp_221_the_market_clock_cost/bench.py`. develop `9ce50725`, 2026-09-10.
3,000 종목 · 1분 execution table · 30분마다 판단 · `no-short` 하나 · record 저장.

| 구성 | run | 비고 |
|---|---|---|
| 300 × 1일 (시장 시계 390점) | 15.7 s | |
| 3,000 × 1일 | 117.4 s | 종목 10배에 7.5배 — **종목 수에 선형** |
| 300 × 3일 | 43.8 s | 점 3배에 2.8배 — 점 수에 선형 |
| 300 × 1일, 포지션 행 끔 | 8.7 s | 포지션 행이 45% |

시장 시계 한 점 × 종목 하나에 약 100 µs. 3,000 종목 분봉이면 하루 2분, 1년 약 8시간.
**일봉(1년 252점)이면 76만 쌍, 약 75초 — 문제가 아니다.** 분봉이 문제다.

3,000 × 1일 117초의 내역:

| 어디 | 초 | 무엇을 하고 있나 |
|---|---|---|
| `normalize_rows` (recorder) | 42 | 프레임워크가 쓴 120만 개 `vqapr.account` 행의 **필드 이름에 공백이 있는지** 행마다 다시 검사. `TableSpec`이 이미 검증한 이름이다 |
| `writer.append` → `_arrow_type` | 21 | 청크마다 모든 값을 훑어 Arrow 타입을 재추론. 타입은 첫 청크에서 정해졌다 |
| `exact_snapshot_rows` + `_exact_row` | 17 | 점마다 duckdb 쿼리 하나(`IN` 3,000개), 행마다 `Decimal(str(price))` |
| `build_account_view` + `ModelWindow` | 13 | compliance가 점마다 3,000개 종목 id를 두 번 재검증 |
| `marking.mark` 등 산술 | 10 | 종목당 Decimal 곱셈. 본질적 비용 |

메모리: 보유 `Mark` 객체가 **점 수 × 종목 수**만큼 run 끝까지 남는다(1일 116,700, 3일 350,700).
매 점의 mark batch가 `lifecycle_trace`와 `occurrences`에 붙어 있고, 마지막에 그것을 읽는 곳은
`contract_report`의 카운트 셋뿐이다. 3,000 종목 1년이면 2.9억 객체.

## 2. 무엇을 어떤 순서로

### P — 성능. 계약 불변. 항목마다 커밋 하나, 벤치마크로 전후를 잰다

| | 무엇 | 예상 (3,000 × 1일) |
|---|---|---|
| P1 | 행은 행으로 모으고 **열로 이동한다.** recorder가 `TableSpec`이 검증한 이름을 다시 검사하지 않는다. 프레임워크 테이블은 `append_columns`. 청크는 `RecordChunk`(열) 하나로 recorder → root/sink → writer를 지난다. writer는 기억한 스키마로 `pa.array`를 바로 만든다 | 42+21 → 10 s |
| P2 | ~~writer~~ P1에 흡수 | |
| P3 | 시장 시계 스냅샷을 **하루 단위로 미리 읽어** 점마다 슬라이스. fill과 mark가 같은 커서를 쓴다. 루프가 정적 병합이라 모든 점을 미리 안다 | 17 → 3 s |
| P4 | 프레임워크가 만든 view·window는 `_trusted` 생성자로. 종목 id 검증은 preflight에서 한 번 | 13 → 1 s |
| P5 | trace와 evidence를 메모리에 쌓지 않고 **접는다.** `contract_report`의 카운트는 온라인으로, mark batch는 record로 나간 뒤 버린다 | 메모리 O(점 × 종목) → O(종목) |

### L — 루프. P가 끝난 코드 위에서

| | 무엇 |
|---|---|
| L1 | 기록 207·205 이식: `_next(**delta)`, run 전체 `sequence` |
| L2 | 시장 시계 한 점을 `MarketInstant` 상태 위의 fold로. 순서는 튜플 하나에 글자로. compliance가 `Marked`를 재구성하지 않고 받는다. P5가 여기 산다 |
| L3 | 루프 하나. `PartHandler`(start·dispatch·finish)가 자기 수신자를 소유. 루프는 `RunStateRepository`·`RunOutput`을 모른다 |
| L4 | 조립 하나: `_run_strategy`/`_run_datamodel`/`freeze_*` 통합 |
| L5 | `Compliance.observe(call)`, 계좌는 `call.account`. `test_a_role_has_one_call.py` 이식 |

### 하지 않는 것

- 배선표가 런타임에 루프를 구동하는 dispatcher — 다섯 행에 과설계이고 파이프라인의 데이터 흐름을 숨긴다.
- datamodel run에 journal을 주는 척추 변경 — 측정된 이득이 없다.
- 패키지 개명(`kit`/`builtin`/`market`/`run`) — 별도 캠페인.
- 포지션 행 계약 변경(체결로 바뀔 때만 쓰기) — 열어 둔다. P1이 행을 10배 싸게 만든 뒤 다시 본다.
- 계산 변경. showcase digest가 그것을 지킨다.

## 3. 게이트

```text
매 항목    uv run pytest tests/ -q          ruff          pyright
           bench.py --names 3000 --days 1   전후 수치를 기록에
P1·P3·P5   횟수 단언 (tests/flow/test_hot_path_costs.py 방식)
착지 전    uv run pytest tests/ -q -m ""    showcase digest 83/83
```

## 4. 결과 (2026-09-10)

```text
3,000 종목 × 1분 execution table × 1일     117.4 s  →  34 s 안팎  (실행 간 잡음 ±25%, 두 번 중 작은 값)
끝난 run이 든 Mark 객체                    1,167,000  →  3,000  (계좌가 든 batch 하나; 점 수에 O(1))
루프 클래스                                2  →  1 (RunLoop · Part · MarketClock)
역할의 콜백                                 넷 다 Call 하나
```

| | 기록 | 3,000 × 1일 |
|---|---|---|
| P1 행은 열로 이동한다 | `221` | 117.4 → 62.3 s |
| P3 execution table을 시장 시계를 따라 미리 읽는다 | `222` | → 45.7 s |
| P4 프레임워크의 view는 두 번 증명하지 않는다 | `223` | → 32.7 s |
| P5 evidence는 요약을 든다 | `224` | Mark 1,167,000 → 3,000 |
| L1 `sequence`는 run의 한 순서 | `225` | record 열 하나 변경, digest 재기록 |
| L2 시장 시계 한 점은 fold | `226` | 다섯 단계 한 모양 |
| L3 루프 하나 | `227` | `RunLoop` · `Part` · `MarketClock` |
| L4 조립 하나 | `228` | `_run_member` · `_window_factory` |
| L5 역할은 Call 하나를 받는다 | `229` | `Compliance.observe(call)` — breaking |

### 설계가 틀린 곳, 게이트가 잡은 곳

- **P3 첫 판은 더 느렸다** (62 → 80 s). 쿼리를 390 → 4개로 줄였지만 Arrow에서 Python으로 건너오는
  셀이 쿼리의 행보다 비쌌다. 열 셋만 변환하고 `trade_at`은 변환하지 않는 둘째 판이 45.7 s.
- **P5는 evidence를 요약으로 바꾼 뒤에도 `Mark`가 그대로였다.** 진짜 보유처는 trace가 든 그 점의
  root였고, 그것을 읽는 곳은 없었다. 가드 테스트가 잡았다.
- **L4 첫 커밋은 테스트 하나를 깨뜨린 채였다.** 게이트 요약 한 줄만 읽었다. `record_ref`를 store 없이
  평가한 것이고, 되돌아가 amend했다. 이후 게이트는 실패 목록까지 읽는다.
- **digest 기준선은 checkout 상대적이었다.** run identity가 소스 경로를 접어 넣으므로 worktree에서는
  `run_id` 열만 다른 record가 나온다. 스크립트가 64자리 hex를 마스킹하게 했다(`221`).
- **머신의 실행 간 잡음이 ±25%다.** 같은 코드로 34 s와 46 s가 나온다. 이후 벤치마크는 두 번 돌려
  작은 값을 적고, 필요하면 임시 worktree로 A/B를 붙였다(`224`).

ExecPlan: `.agent/plans/completed/one-loop-campaign.md`.
