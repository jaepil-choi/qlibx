# 두 시계 캠페인 — 배선표를 문서에서 코드로 옮긴다

Status: completed (2026-09-10, records `201`-`214`)

## Purpose

`vqapr`가 **매 분 판단하고 매 분 체결하는 전략을 표현할 수 있게** 하고, 그 과정에서 드러난 배선
(무엇이 언제 불리고 답이 누구에게 가는가)을 산문이 아니라 코드로 만든다.

관측 가능한 결과 넷.

1. 매 분 판단 · 매 분 체결 전략이 showcase로 돌아간다. 지금은 어휘가 없어 표현되지 않는다.
2. `vqapr`가 dataset 그래프를 안다 — 무엇이 무엇에서 나왔는지, 무엇이 아직 없는지를 실행 전에 답한다.
3. 확장점이 넷이고 각각의 시계와 수신자가 코드에 있다. `Constraint`가 빠지고 `Compliance`가 들어온다.
4. 계좌가 append-only 원장이 되어, 죽은 run이 손상된 상태가 아니라 짧은 이야기를 남긴다.

**설계 근거는 이 계획이 아니라 [`docs/design/two-clocks-and-the-wiring-table.md`](../../../docs/design/two-clocks-and-the-wiring-table.md)에 있다.**
왜 그렇게 정했는가는 거기, 무엇을 어떤 순서로 하는가는 여기.
캠페인 개요는 [`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`](../../../docs/refactoring/2026-09-09-the-two-clocks-campaign.md).

## Scope and non-goals

### 범위

```text
선언과 preflight   writes 필수 · run = 전략 하나 · agenda 어휘 · 체결 시각 어휘 · 종목 게이트
시계와 단계        시장 시계 1급 · VALUATION 단계화 · 순서 고정 · ACCRUE 빈 자리
역할               Constraint 제거 · Compliance 신설 · Exchange 계약 좁힘
통장               LedgerEntry · Account = append 권한 · Prepared* 통합 · freeze 축소
구조               배선표 코드화 · 부품/도구 · 패키지 재배치
```

### 범위 밖

```text
Accrual 구현            M9 는 빈 handler 와 배선만
origin 구조화           지금은 라벨.  TWR 이 필요해질 때 다시
다중 venue              run 당 Exchange 하나
partial fill · child order · TWAP · 큐 포지션      PRD §13 그대로
live wall-clock         아키텍처 §15-5 그대로
성능 최적화             이 캠페인은 성능 작업이 아니다.  M6 이 촘촘한 격자에서
                        VALUATION 을 더 자주 돌게 만드는 것은 의도된 동작이다
```

## Constraints

- **breaking change 허용** (소유자, 2026-09-09). 사용자 확장점 계약이 바뀐다. major 경계로 나간다.
- **국소 정리 금지.** 파일 하나 옮기기는 경계를 다시 그으면 덮어써지므로 이 캠페인 안에서만 한다.
- **`tests/boundaries/test_the_layers_hold.py`의 `OPEN`은 비어 있고 그대로 비어 있어야 한다.**
  한 마일스톤이 간선을 열어야 하면 그 표에 적고 **같은 커밋에서 닫는다.**
- **패키지 이름은 M12 전에 정하지 않는다.** 무엇을 하는지가 끝난 뒤에 정한다(아키텍처 §10).
- 각 마일스톤은 **독립적으로 착지 가능**해야 한다. M5까지만 하고 멈춰도 트리는 일관되고 매 분
  전략이 표현된다.

## Acceptance criteria

| | |
|---|---|
| AC-1 | 매 분 판단 · 매 분 체결 전략이 `tests/showcases/`에서 돈다. 하루 390 콜백, 390 체결 후보, 판단한 만큼 체결 |
| AC-2 | `at` 없는 체결 어휘로 "결정 이후 첫 시장 시계 점"이 표현된다. `SAME_DAY`/`local_time` 어휘는 트리에 없다 |
| AC-3 | agenda가 `every`/`from`/`to`/`at` 선언에서 preflight로 전개된다. 거래일은 execution table이 답한다 |
| AC-4 | `writes` 없는 run 선언이 등록에서 거절된다. 등록된 run의 `reads`/`writes` 관계를 조회할 수 있다 |
| AC-5 | run 선언에 `strategies:` 배열이 없다. run 하나가 전략 하나다 |
| AC-6 | instrument 선언 0개면 preflight가 거절한다. 미등록 종목 주문은 runtime 실패이고, 미등록 종목을 **전부 모아서** 보고한다 |
| AC-7 | `PendingValuation`이 트리에 없다. Hold는 아무것도 예약하지 않는다. 평가는 시장 시계 점마다 일어난다 |
| AC-8 | 한 시각의 순서가 ACCRUE → EXECUTE → VALUATION → COMPLIANCE → DECIDE로 고정되고 테스트가 그것을 지킨다 |
| AC-9 | `Constraint`가 확장점 목록에 없다. 내장 둘은 사용자가 콜백에서 부르는 순수 함수다 |
| AC-10 | `Compliance`가 확장점이고, 시장 시계 위 VALUATION 직후에 불리며, 구독과 기억을 갖는다 |
| AC-11 | `Exchange`가 종목 사전을 받는다. venue 설정 스키마는 venue가 소유한다 |
| AC-12 | `LedgerEntry` 한 모양으로 통장이 돈다. `Prepared*` 셋이 하나다 |
| AC-13 | 배선표가 코드에 있고, 부품/도구 구분이 타입에 있다 |
| AC-14 | 매 마일스톤에서 `test_all` · `ruff` · `pyright` 통과. M6·M7·M11·M12에서 record 회귀 비교 통과 |

## Repository context

기준: `develop @ 1c974672`, 2026-09-09.

### 시계와 루프

```text
flow/engine/loop.py        142   EventLoop.  얼린 occurrence + 실행 중 생기는 due 를 한 시계로 합친다
flow/strategy/loop.py      283   StrategyEventLoop.  handle() 이 OccurrenceEvent / DueEvent 로 분기
flow/strategy/callback.py  768   decide -> intent.  _accept_valuation() 이 PendingValuation 을 만든다
flow/strategy/execution.py 349   intent -> 주문 -> 체결 -> commit
flow/strategy/valuation.py 406   mark -> 계좌, 그리고 monitoring
flow/strategy/context.py   608   FlowContext · AcceptedIntent · PendingValuation
flow/datamodel/{loop,compute,output}.py   datamodel kind
```

**핵심 사실.** pending 슬롯이 하나이고 `AcceptedIntent`와 `PendingValuation` 둘 다 담는다
(`loop.py:_dispatch_pending`). Hold는 `_accept_valuation`으로 평가를 예약한다 — 평가에 자기 시계가
없어서 pending 슬롯에 얹혀 탄 것이다. **M6이 이것을 없앤다.**

### 선언과 preflight

```text
flow/declaration/run.py         663   RunDefinition · RunExecution · RunFill · StrategyEntry
flow/declaration/preflight.py   841   §12 검사 전부
flow/declaration/frozen.py      429   FrozenRun · FrozenStrategy · FrozenDataModel + identity
flow/declaration/judgments.py   651   check 가 내리는 판정
flow/orchestration.py           751   run 하나 = 멤버 여럿 (record 139)
domain/agendas.py               228   OperationAgenda · OperationOccurrence.  recurrence 해석 없음
project/{run,registration,document,merge,state,store}.py   워크스페이스
```

### 체결

```text
exchange/conventions.py      301   FillSelector(SAME_DAY|NEXT_ELIGIBLE) · FillConvention
                                   (selector + local_time + timezone) · ExecutionHorizon
                                   · ExactExecutionTarget
exchange/execution_table.py  547   ExecutionTable 바인딩 · ExactExecutionSnapshot
exchange/listings.py         608   TradeRule · ExchangeRulesView · TradeTerms
exchange/planning.py         489   plan_orders (닫힌 함수)
exchange/venue.py            208   Exchange ABC · ExecutionCall · AcademicExchange
exchange/venues/krx.py       461   KRX 프로파일.  docstring 이 "구현함 / 구현 안 함" 을 산문으로 적는다
```

**핵심 사실.** `ExecutionHorizon`이 execution table의 instant 집합을 run 내내 들고 있고
(`after(decision_time)`이 결정보다 늦은 후보를 잘라준다), `FillConvention.resolve_local_target(day)`가
**날짜당 시각 하나**를 만든다. **기계는 이미 있고 어휘가 좁다.** M5가 어휘를 넓힌다.

### 계좌

```text
account/account.py          356   Account · AccountMode(LONG_ONLY|SIGNED) · JournalEntry
                                  · PreparedAccountFill · PreparedAccountTransition
                                  · PreparedAccountValuation · _appends_one_mark
account/marking.py          145   ValuationService
domain/account_state.py           AccountSnapshot · AccountMark · AccountState
                                  (snapshot + mark_history + fill_history: tuple[object, ...])
flow/engine/run_state.py    733   RunStateRepository · LifecycleKind.  Prepared* 셋을 전부 import
flow/freeze.py              364   엔진 값 -> record 모델 번역
record/{schema,reader,writer}.py  디스크 위의 record
```

### 제약

```text
authoring/component.py            Component · DataModel · StrategyModel · Constraint(project+monitor)
constraints/evaluation.py   412   project_constraints · merged_constraint_bounds
                                  · evaluate_constraints · build_account_view
constraints/builtin/no_short.py           75
constraints/builtin/single_name_cap.py   211
```

**핵심 사실.** `constraints/evaluation.py`가 `flow/strategy/callback.py`(project)와
`flow/strategy/valuation.py`(monitor) **양쪽에서** 불린다. 두 반쪽이 서로 다른 시계 위에 산다는
증상이다.

### 게이트

```text
tests/boundaries/test_the_layers_hold.py   LAYERS 표 + OPEN(비어 있음)
tests/showcases/                            8 개 (show_003 은 gitignored 데이터를 읽어 수동)
tests/acceptance/ · tests/characterization/ · tests/qa/
```

## Milestones

- [x] **M0** 준비 — 회귀 기준선과 문서 표시
- [x] **M1** run은 전략 하나 + `--jobs`가 run들을 병렬로 (`4c7a7430`, record `201`)
- [x] **M2** `writes` 필수 + strategy가 배분을 공개 (record `202`)
- [x] **M3** instrument 선언 게이트 — `roster.absent` · `instrument.undeclared` (record `203`)
- [x] **M4** agenda 어휘 `every`/`from`/`to`/`at` + preflight 전개 (record `204`)
- [x] **M5** 체결 시각 어휘 — **Stage 1 완료.** AC-1 매 분 전략 acceptance (record `205`)
- [x] **M6** 시장 시계 1급 + VALUATION 단계화 (`PendingValuation` 제거) (record `206`)
- [x] **M7** 단계 순서 고정 + ACCRUE 빈 자리 — **Stage 2 완료** (record `207`)
- [x] **M8** `Constraint` 확장점 제거 → 순수 함수 (record `208`, M9와 한 커밋)
- [x] **M9** `Compliance` 신설 (record `209`)
- [x] **M10** `Exchange` 계약 좁힘 + 종목 사전 — **Stage 3 완료** (record `210`)
- [x] **M11** `LedgerEntry` + `Account` = append 권한 (record `211`)
- [x] **M12** `Prepared*` 통합 + `freeze` 축소 — **Stage 4 완료** (record `212`)
- [x] **M13** 배선표 코드화 + 부품/도구 타입 (record `213`)
- [x] **M14** 패키지 재배치 + `flow/datamodel`·`flow/strategy` 통합 — **Stage 5 완료, 캠페인 완료** (record `214`)

### M0 — 준비

**한다.** 현재 showcase 8개의 record를 기준선으로 캡처한다(M6·M7·M11·M12의 회귀 비교 대상).
`docs/vqapr-prd.md`와 `docs/vqapr-architecture.md`에서 설계 문서 §8이 뒤집는다고 적은 절 옆에
포인터 한 줄씩 — 본문을 고치지는 않는다. 캠페인이 끝나면 architecture가 흡수한다.

**검증.** 기준선 record가 재생성 가능하다(같은 선언으로 두 번 돌려 같은 record).

### M1 — run은 전략 하나

**왜 먼저인가.** M2의 `writes`가 하나인지 리스트인지를 이것이 정한다.

**조사 결과 (2026-09-09).** 선언은 `project/run.py`에 있다 — 아키텍처 문서가 적은
`flow/declaration/run.py`는 없다. `RunDefinition`이 `strategies: tuple[StrategyEntry, ...]`와
`datamodels: tuple[DataModelEntry, ...]`를 갖고, `_whole_declaration`이 *둘 중 하나만*을 강제한다
(record `148`). 소비자는 약 30곳 — `frozen.py`(`layers`·`strategy(id)`·`datamodel(id)`·`kind`),
`orchestration.py`(멤버 루프 + `_in_workers`), `preflight.py`, `judgments.py`, `freeze.py`,
`strategy/loop.py`, `datamodel/loop.py`, `cli/{run,list_,rm}.py`, `project/document.py`.

**그리고 하나 걸린다.** `vqapr run <target> --jobs N`이 **run 하나의 멤버들**을 병렬로 돈다.
전략 하나가 되면 병렬화할 단위가 사라지는데 그래프 스케줄러는 M2 이후다. 대체 없이 없애면
"각 마일스톤은 독립적으로 착지 가능"을 깬다. 다리는 짧다 — `_in_workers`의 워커는 이미
*"레지스터된 run을 다시 얼리고 그중 전략 하나를 돈다"*이므로 단위만 바꾸면 된다.

**그래서 둘로 나눠 연달아 착지시킨다.**

#### M1a — 선언과 실행이 멤버 하나만 받는다

`RunDefinition`의 두 튜플을 단일 엔트리로. 저장된 spelling(component id로 키된 매핑)도 하나로.
`FrozenRun`의 `layers`/`strategy(id)`/`datamodel(id)`를 하나로. `orchestration.py`의 멤버 루프
제거. `--jobs`는 단일 멤버 run에서 무의미하므로 그 자리에서 분명한 메시지를 남긴다.

**record 경로는 유지한다.** `runs/<run_id>/strategies/<ref>/tables/...`의 `strategies/` 층이
단일 항목 디렉터리가 될 뿐이다. 평탄화는 별도 결정이고 M1에서 하지 않는다 — 기준선 digest가
그것을 지킨다.

#### M1b — `--jobs`가 run들을 병렬로 돈다

`vqapr run`이 target을 여럿 받고, `--jobs`가 그 사이를 병렬화한다. `_in_workers`의 단위를
"run 안의 멤버"에서 "run"으로 바꾼다. 설계 §2.3이 말한 자리다.

**검증.** 기존 다중 전략 선언이 명확한 메시지로 거절된다. 다중 전략을 쓰던 showcase가 개별
run으로 갈라져 **같은 record**를 낸다(digest 경로만 바뀌고 내용은 그대로여야 한다).
`--jobs`가 여러 run에 대해 작동한다.

### M2 — `writes` 필수 + 그래프

**한다.** 선언에 `writes` 추가(이름만, 필수). preflight가 이름 충돌·미존재 재료를 실행 전에 거절.
워크스페이스가 `reads`/`writes` 관계를 저장하고 `vqapr list`가 그것을 보여준다.
`flow/datamodel/output.py`의 사후 등록을 **선언된 이름으로의 등록**으로 바꾼다.

**검증.** `writes` 없는 선언이 거절된다. `ensemble`의 재료가 없으면 실행 전에 그 사실을 말한다.
lineage 조회가 된다.

### M3 — instrument 선언 게이트

**한다.** preflight: 선언 0개면 거절. runtime: 주문에 미등록 종목이 있으면 실패하되 **미등록 종목을
전부 모아서** 보고. `flow/roster.py`와 `exchange/venue.py`의 `ExecutionCall`에 종목 사전 경로.

**검증.** 세 집합이 독립임을 증명하는 테스트 — execution table에 ETF가 섞여 있고 주식만 선언하고
주식만 주문하면 돈다.

### M4 — agenda 어휘

**한다.** `every`/`from`/`to`/`at`을 선언에 추가. preflight가 execution table의 **거래일**(날짜만,
시각 아님) 위에서 전개해 `OperationAgenda`를 만든다. 전개 결과의 identity를 얼린다.

**경계.** 날짜는 유도하고 시각은 유도하지 않는다(설계 §3.3). 밀도를 바꿔도 거래일 집합이 같다는
것을 테스트가 지킨다 — `UC-TIME-002`의 보장.

**검증.** 1분 테이블과 일별 테이블이 같은 월간 agenda를 만든다. 97,500 occurrence 전개가 된다.

### M5 — 체결 시각 어휘 (Stage 1 완료)

**한다.** `FillSelector`(SAME_DAY|NEXT_ELIGIBLE)와 `local_time`+`timezone` 조합을 없애고
**"결정 이후 첫 시장 시계 점"** 을 기본으로. 선택 손잡이 `at`/`after`/`within` 추가.
`ExecutionHorizon.after()`가 이미 후보를 잘라주므로 그 위에 얹는다.

**검증 (AC-1, AC-2).** 매 분 판단 · 매 분 체결 전략이 showcase로 돈다. 기존 일별 종가 체결
showcase가 새 어휘로 같은 결과를 낸다.

### M6 — 시장 시계 1급 + VALUATION 단계화

**한다.** `EventLoop`가 세 번째 소스를 받는다 — execution table의 모든 instant. `PendingValuation`
삭제. Hold는 아무것도 예약하지 않는다. 평가는 시장 시계 점마다 일어난다. pending 슬롯은
`AcceptedIntent`만 담는다.

**위험.** 이 캠페인에서 가장 크다. 일별 격자에서는 지금과 같아야 하고, 촘촘한 격자에서 처음으로
다르다(그것이 의도).

**검증 (AC-7).** M0의 기준선 record와 일별 showcase가 **바이트 단위로** 일치한다.

### M7 — 단계 순서 고정 + ACCRUE 자리 (Stage 2 완료)

**한다.** 한 시각의 순서를 ACCRUE → EXECUTE → VALUATION → COMPLIANCE → DECIDE로 고정.
ACCRUE는 아무것도 하지 않는 handler와 배선만. 순서를 지키는 테스트를 `tests/boundaries/`에.

**검증 (AC-8).** 순서 테스트. 기준선 회귀.

### M8 — `Constraint` 확장점 제거

**한다.** `authoring/component.py`에서 `Constraint` 제거. `constraints/builtin/` 둘을 사용자가
콜백에서 부르는 **순수 함수**로. `constraints/evaluation.py`의 `project_constraints` ·
`merged_constraint_bounds`도 함께. `flow/strategy/callback.py`에서 제약 호출 경로 제거.
`extension/`의 `ComponentKind`에서 constraint 제거. scaffold · shipped skills 갱신.

**잃는 것 기록.** §7.1의 *"constraint별 before/after 보존"*이 프레임워크 보장에서 전략이 직접
기록하는 것으로 내려간다. 구현 기록에 적는다.

**검증 (AC-9).** enhanced-index showcase가 순수 함수 조합으로 같은 결과를 낸다.

### M9 — `Compliance` 신설

**한다.** 확장점 `Compliance` — 시장 시계 위 VALUATION 직후, 구독 + 기억, committed 계좌를 관측,
finding을 게시판으로. 전략의 값을 물려받지 않는 **독립 파라미터**. `constraints/evaluation.py`의
`evaluate_constraints`·`build_account_view`가 여기로 옮겨오되 시계가 바뀐다.
`vqapr.monitoring` 기록 테이블은 유지.

**검증 (AC-10).** 판단이 없는 날에도 breach를 잡는다(`UC-EXEC-003`). 관측만 하는 Compliance가
bound 없이 등록된다.

### M10 — `Exchange` 계약 좁힘 (Stage 3 완료)

**한다.** `ExecutionCall`에 종목 사전 추가(M3의 경로를 계약으로). venue 설정 스키마를 venue가
소유하도록 — KRX의 규칙 on/off. `venues/krx.py` docstring의 *"구현함 / 구현 안 함"* 을 선언으로.

**검증 (AC-11).** 거래세를 끈 KRX가 같은 선언으로 돌고 다른 결과를 낸다. 두 run이 다른 identity를
갖고 창고에 따로 들어간다.

### M11 — `LedgerEntry` + `Account` = append 권한

**한다.** `LedgerEntry`(`at`·`cash`·`positions`·`origin`·`detail`)를 `domain/`에.
`AccountState`를 append-only 원장 + 증분 fold로. `Account`는 append 허가만 — 결과 상태 유효성과
버전 순서만 검사하고, 출처별 불변식은 생산자에게. `_appends_one_mark` 삭제.
`retained_marks`를 원장 밖 메모리 창의 성질로 분리. `fill_history: tuple[object, ...]`에 타입.

**검증 (AC-12).** 기준선 회귀. 중간에 죽은 run이 유효한(짧은) 원장을 남긴다는 테스트.

### M12 — `Prepared*` 통합 + `freeze` 축소 (Stage 4 완료)

**한다.** `PreparedAccountFill`·`PreparedAccountTransition`·`PreparedAccountValuation` 셋을
"검증된 항목 하나"로. `flow/engine/run_state.py`의 세 갈래 publication을 한 갈래로.
`flow/freeze.py`에서 엔진 값 → record 모델 번역 중 사라지는 부분을 지운다.

**검증.** 기준선 회귀. 실제 감소량을 Progress에 기록한다 — 예측이 빗나갔으면 그 사실도.

### M13 — 배선표 코드화 + 부품/도구

**한다.** `Role` base를 얇게(구독 + 기억 + 콜백 하나). 시계와 수신자를 배선표로. 부품/도구 구분을
타입에 — **부품 = 도구 + 시계.** 배선표를 지키는 테스트.

**검증 (AC-13).** 새 역할을 추가하려면 배선표에 행을 더해야 한다는 것을 테스트가 강제한다.

### M14 — 패키지 재배치 (Stage 5 완료)

**한다.** 이름을 **여기서 정한다** (M12까지의 결과를 보고). `flow/datamodel`과 `flow/strategy`
통합 — 시계가 하나냐 둘이냐의 차이만 남는다. `LAYERS` 표 갱신.

**검증.** `test_the_layers_hold` 통과, `OPEN` 비어 있음. `public.py` export 고정 테스트 갱신.

## Progress

- 2026-09-09 — 설계 문서와 캠페인 문서 확정, 매니페스트 갱신 (`1c974672`, `771280e4`). ExecPlan 작성.
- 2026-09-09 — 브랜치 `redesign/two-clocks` 생성 (`develop @ 771280e4`에서).
- 2026-09-09 — **M0 전반 완료** (`5cbb61a6`). `scripts/showcase_record_digest.py` +
  `tests/showcases/baseline-record-digest.json` (81 entries / 6 showcases). 정리 후 재실행에서
  81/81 일치 — 기준선이 재생성 가능함을 확인.
- 2026-09-09 — **M0 후반**: PRD 6곳 · 아키텍처 3곳에 캠페인 포인터 삽입. 본문은 안 고쳤다.
- 2026-09-09 — **ruff 82건을 닫았다** (`380ca92b`). 캠페인이 만든 것이 아니라 `6cb3f254`의 회귀였다.
  이제 선언된 lint 게이트가 초록이라 "신규 위반 0"이 판정 가능하다.
- 2026-09-09 — **M1 (M1a+M1b 합침)**: 선언·freeze·실행이 멤버 하나만 받고, `--jobs`가 run들을
  병렬로 돈다. `in_workers`의 단위가 "run 안의 멤버"에서 "run"으로 바뀌었고 워커에서
  `component_id`가 빠졌다. CLI `run`이 target을 여럿 받고 envelope에 `runs:`가 생겼다.
  테스트 26개 파일 수습, `test_a_run_holds_several_strategies.py` 삭제.
- 2026-09-09 — **M2**: `writes` 필수(두 kind 공통, 이름만), 저장 spelling `strategy:`/`datamodel:`
  (옛 spelling은 읽힌다), `DataModelOutput` → `RunOutput`으로 strategy run이 `vqapr.weight`를
  `<writes>`로 공개, `run.output_registered`가 두 kind에, `_judge_member_datasets`가 미등록 재료의
  생산자를 가리킨다. 자기-산출물 규칙(설계 §2.1)이 `show_001`에서 나와 `_own_output_or_refuse`로
  들어갔다. 1608 passed · ruff · pyright 0 · digest 기준선 재기록(67/81 — `run_id` 열 하나, 아래
  발견). 기록 `202`.
- 2026-09-09 — **M3**: strategy run은 roster 없이 안 돈다. preflight·`check`가 `roster.absent`(412),
  runtime이 주문 계획 전 새 단계 `simulation.due.instrument_declaration`에서 `instrument.undeclared`로
  미등록 종목을 **전부** 모아 거절. `public.register_instruments`(export+register 한 문) 신설, sample이
  roster를 materialize 시점에 export·선언, showcase 003·007이 roster 등록, 픽스처 7곳 갱신, 스킬 3곳.
  1619 passed · ruff · pyright 0 · digest 4/81(show_007 fill `kind`·record `roster`) 재기록 →
  81/81. 기록 `203`.
- 2026-09-09 — **M4**: `agenda: {every, at | from/to, days_from}` 블록이 `sessions`/`sessions_from`/`at`을
  대체. 날짜는 데이터(strategy: execution table, datamodel: `days_from`), 시각은 규칙. 도메인에
  `AgendaRule` + `OperationAgenda.expand`, occurrence id `{agenda}-{date}T{HHMM}`. 옛 spelling은
  거절(다시 등록). 테스트 33개 파일·showcase 8개·스킬 6개 sweep. 1634 passed · ruff · pyright 0 · digest 17/81(strategy/datamodel.json의 agenda 블록만;
  run.json·테이블 불변 — identity는 agenda 이름을 안 접는다) 재기록 → 81/81. 기록 `204`.
- 2026-09-09 — **M5 (Stage 1 완료)**: `FillRule(trade_price, timezone, at?, after?, within?)`이
  `FillConvention`/`FillSelector`/fold·offset을 대체. 기본 = 결정 이후 첫 execution instant.
  `trade_price`는 `execution:`으로, fill의 `timezone`은 run의 것. `_judge_execution_ordering`이
  테이블에 묻는다. AC-1 acceptance(1분 테이블, `every: 1m`, fill 없음 → 매 분 다음 분에 체결).
  32개 파일 sweep(한 번에). 1642 passed · ruff · pyright 0 · digest 60/81(`run_id` 열; M4 worktree와 `run_id` 뺀
  테이블 비교로 AC-2 확인) 재기록 → 81/81. 기록 `205`.
- 2026-09-09 — **M6**: `EventLoop`가 정적 소스 둘(`OccurrenceEvent` ∪ `MarketEvent`)의 정렬 병합이 됐다;
  `DueEvent`·`pending()`·`PendingValuation` 삭제. 시장 시계 점마다 EXECUTE(target이 그 시각인 pending)
  또는 VALUATION+COMPLIANCE(`value_at`, pending 보존). Hold는 아무것도 예약하지 않는다. AC-1
  acceptance 확장(열한 시각 전부 평가 · `after: 5m`으로 pending 생존과 교체). 1641+9 passed · ruff · pyright 0 · **digest 81/81 재기록 없이 (AC-7)**. show_001의
  서명을 outcome/market_clock으로 갈랐다(평가 횟수는 밀도를 따라 커져야 한다). 기록 `206`.
- 2026-09-09 — **M7 (Stage 2 완료)**: `_handle_market`이 순서표(ACCRUE → EXECUTE → VALUATION → COMPLIANCE;
  DECIDE는 뒤에 정렬). `execute_due` → `fill`/`close`, mark는 `ValuationHandler.mark_fill`/`mark_held`로,
  `AccrualHandler` 빈 자리 + `MARKET_ACCRUE` stage. AC-8 boundary test 둘(소스 순서 · 실행 순서).
  1643 passed · ruff · pyright 0 · **digest 81/81 재기록 없이**. 기록 `207`.
- 2026-09-09 — **M8 + M9 (한 커밋)**: `Constraint` 확장점이 사라지고 `vqapr.portfolio.bounds`의 kit
  (`no_short` · `single_name_cap` · `intersect`, 순수 함수, `(lower, upper)`)이 전략 콜백 안으로;
  `Compliance` 확장점 신설 — `observe(call, account)` 하나, 시장 시계 VALUATION 직후
  (`ComplianceHandler`, `MARKET_COMPLIANCE`), 구독+기억, 독립 파라미터(box를 물려받지 않는다).
  선언은 run의 `compliance: [...]`(`exchange:` 옆), `FrozenStrategy.compliance`가 identity를 접는다.
  `vqapr.monitoring`의 `constraint` 열 → `rule`, record `constraints` → `compliance`, report
  `ComplianceSummary.rule`. showcase 003·005·006·008이 kit + 등록된 규칙으로(006·008은 벤치마크를 새로
  구독), skill `make-constraint` → `make-compliance`(+ `the-box.md`, `observe.md`), scaffold
  `vqapr new compliance`. 테스트 40여 파일 sweep, `tests/constraints` → `tests/compliance`,
  `tests/portfolio/test_bounds.py`. 1643 passed · ruff · pyright 0 · digest 16/81(strategy.json의 `constraints`→`compliance` 키 14 + show_003 datamodel record 2 신규; 테이블 0) 재기록 → 83/83, AC-9는 M7 worktree 비교(parquet 53개 `run_id` 빼고 동일 + manifest의 index/ensemble 블록 동일). 기록
  `208`·`209`.

- 2026-09-09 — **M10 (Stage 3 완료)**: `ExecutionCall.instruments`(종목 사전, `InstrumentRoster` 통째)가
  계약의 필드가 됐고 `rules`는 거기 묶인다(다른 사전에 묶인 view는 거절). `Exchange.settings`(strict JSON,
  스키마는 venue의 것) 신설, `load_exchange`가 검사, `strategy.json`에 `exchange: {component_id, fingerprint,
  settings}` 블록. `KrxExchange(ids|listings, *, commission_rate, sale_tax_rate, price_limits)` +
  `KrxSettings` + `KRX_NOT_MODELLED` — docstring의 "구현함/구현 안 함"이 데이터. AC-11 acceptance(한 파일 두
  config → 두 venue·두 identity·두 창고 데이터셋). **발견·수정: 저장된 run이 `writes`를 창고에 안 넣고
  있었다**(`recorder_rows`가 비어서) — record에서 읽어 공개, 명령이 연 workspace로 등록.
  1652 passed · ruff · pyright 0 · digest 14/83(strategy.json의 `exchange` 블록 신설; 테이블 0) 재기록 → 83/83. 기록 `210`.

- 2026-09-10 — **M11 (Stage 4 시작)**: `domain/ledger.py`의 `LedgerEntry(at, cash, positions, origin,
  detail)` + `fill_entries`; `fold`는 `account_state.py`에. `AccountState(snapshot, marks, ledger)` =
  fold + 창 + 마지막 append. `Account.append/mark/commit_append/commit_mark` 네 문 — `prepare_fill`·
  `prepare_mark`·`prepare_valuation`·`Prepared*` 셋·`JournalEntry`·`_appends_one_mark` 삭제.
  `vqapr.fill` 행은 `LedgerEntry.detail`에서. **발견·수정: 죽은 run이 fill 테이블을 안 남겼다**
  (fill 행이 root chunk에만 쌓여 끝에서만 디스크에 닿음) → `_stage_rows`로 스트리밍. AC-12 acceptance
  (셋째 결정에서 죽는 전략의 디스크 fill을 fold → 마지막 account 행과 일치). 1654 passed · ruff ·
  pyright 0 · **digest 83/83 재기록 없이** (둘째 척추 변경, record 불변). 기록 `211`.

- 2026-09-10 — **M12 (Stage 4 완료)**: run_state의 일곱 `prepare_*`가 `_advance(root, **changes)` 하나로
  다음 루트를 만든다(바꾸는 것만 이름 짓는다). 계좌 세 갈래 → `prepare_account(PreparedAppend | PreparedMark)`
  하나, `publish_*` 다섯 → `publish_infallible` 하나. **감소량(측정): run_state 731 → 632줄,
  account.py 356 → 252(M11), freeze.py 0줄** — freeze의 "번역 중 사라지는 값"은 없었다(예측 빗나감,
  `212`에 적음). 1654 passed · ruff · pyright 0 · **digest 83/83 재기록 없이**. 기록 `212`.

- 2026-09-10 — **M13 (Stage 5 시작)**: `domain/wiring.py` — `Role`·`Clock`·`View`·`Receiver`·`Wiring`,
  §4의 다섯 줄이 닫힌 표 `WIRING`으로, `MARKET_CLOCK_ORDER`(§3.1). `Part`·`Tool`이 `Component` 아래(부품 =
  도구 + 시계): `DataModel`·`StrategyModel`은 Part, `Exchange`·`Compliance`는 Tool, 클래스마다 `ROLE`과
  `wiring()`, `ComponentKind.role`. §10.2 결정: 표는 데이터, 타입은 부품/도구 하나만. AC-13 테스트
  (`Role` ↔ 행 일대일, 표 = 설계, parts/tools, kind ↔ role, `_handle_market` 순서 = 표). 1660 passed · ruff ·
  pyright 0 · digest 83/83 재기록 없이. 기록 `213`.

- 2026-09-10 — **M14 (Stage 5 완료, 캠페인 완료)**: `flow/strategy/` + `flow/datamodel/` → **`flow/run/`** 하나,
  시계로 배열(loop · callback/compute = 전략 시계 · accrual/execution/valuation/compliance = 시장 시계 ·
  context · output). 두 루프가 `run/loop.py` 한 파일에 나란히 — 차이는 시계 수뿐. `git mv`(여덟 모듈
  내용 불변), 비공개 재수출 둘 제거, `tests/flow/run/` 미러, `LAYERS`의 `flow.run: 65`, `OPEN = {}`.
  §10.1 결정: `flow/run/` (`project/run` 선언 · `cli/run` 명령 · `flow/run` 실행). `Role`은
  `ComponentKind`를 흡수하지 않는다(등록 가능한 넷 ≠ 행 다섯; `ComponentKind.role`이 잇는다). 루프
  클래스 하나로 접기는 척추 변경이라 안 했다(`214`에 이유). 1660 passed · ruff · pyright 0 ·
  digest 83/83 재기록 없이. 기록 `214`.

## Discoveries

### M13에서 발견한 것 (2026-09-10)

- **표를 데이터로, 타입은 하나의 사실만.** 비교·나열·세기는 표가 하고, 코드가 강제할 구조는 부품/도구뿐이다.
- **`Receiver`는 넷이다** — §5의 셋에 중계 하나(`EXCHANGE`). 셋으로 접으면 표의 "주문 → Exchange"가 거짓이 된다.

### M12에서 발견한 것 (2026-09-10)

- **freeze.py에는 지울 번역이 없었다.** record 필드로 안 나오는 값이 없고, `contract_report`의 duck-typed
  읽기는 SimpleNamespace 테스트가 기대는 문이다. 예측이 빗나간 것을 그대로 적었다.
- **`prepare_marked`와 `prepare_valuation_only`의 차이(pending)는 관찰 불가였다** — append가 먼저 pending을
  비운다. 접어도 lifecycle 순서(AC-8)가 그대로다.

### M11에서 발견한 것 (2026-09-10)

- **fill 행은 스트리밍되지 않고 있었다.** `prepare_account_commit`이 root chunk에 직접 넣고 `new_rows`를
  안 채워, `freeze_strategy_record`의 잔여 행 쓰기가 완주 run에서 가려 줬다. 죽는 run으로만 보인다.
- **`domain/ledger` ↔ `domain/account_state` 순환은 배치로 푼다.** `fold`를 snapshot 옆에 두면 지연
  import가 필요 없다. deferred-import 상한이 잡았다.
- **ruff `--fix`가 지운 `# noqa`를 겨눈 치환은 조용히 빗나간다.** 치환은 count를 단언한다.

### M10에서 발견한 것 (2026-09-09)

- **`vqapr run`은 M2 이후 allocation을 공개한 적이 없다.** `_publish_allocation`이 root의 `recorder_rows`를
  읽는데 store가 있으면 행이 record로 흘러가 root에 없다. showcase는 record에서 손으로 등록해서 못 봤다.
  store 유무로 갈리는 경로는 둘 다 테스트한다.
- **빈 사전은 사전 없음이 아니다.** `ExchangeRulesView.notional`의 registry-None fallback은 빈 roster에서
  타지 않는다. call이 항상 사전을 나르므로 venue 테스트 더블은 사전을 묶는다(`tests/exchange/support.py::bound`).
- **`price_limits`는 listing의 사실이지 설정이 아니다.** 두 곳에서 말하면 갈린다 — id로 받을 때만 스위치,
  rule로 받으면 rule이 말한다.

### M8·M9에서 발견한 것 (2026-09-09)

- **`StrategyEntry`(pydantic dataclass)의 kwarg는 `model_validator(mode="before")`에 Mapping으로
  안 온다.** 이름으로 거절하는 자리는 `RunDefinition`이 strategy 블록을 읽는 곳이다.
- **arity 픽스처는 계약이 줄면 무력화된다.** `monitor(self, account, marks)`는 4에 대해 짧았지만 3에는
  딱 맞는다. 세 파일에서 `observe(self, account)`로.
- **"모든 문제를 한 번에 보고한다" 테스트는 두 멤버짜리 kind가 있어야 한다.** Compliance는 하나,
  Strategy는 loader가 `decide`를 먼저 거절한다. 테스트를 지우고 `208`에 적었다.
- **showcase 006·008은 벤치마크를 구독하지 않고 벤치마크 상대 cap 안에서 최적화하고 있었다.**
  constraint의 `inputs()`가 그것을 숨겼다 — 설계 §7.1이 말한 "부수적으로 정직해지는 것".
- **`due_boundary`의 owner는 `ComplianceSet`이다.** 규칙 하나를 가리키면 나머지 규칙의 관측이
  사라진다. 단위는 "이 시각의 COMPLIANCE".


- **모델은 이미 매 분 거래를 지원한다.** 동일 시각 우선순위(아키텍처 §3.2: 체결 → 반영 → 평가 →
  판단), 최소 간격(`execution_time > decision_time`), pending 교체 규칙이 전부 옳다. 빠진 것은
  `FillConvention`의 어휘 하나였다. 이 발견이 M5를 M6보다 앞에 둔 이유다.
- **`ExecutionHorizon.after(decision_time)`이 이미 존재한다** — "결정보다 늦은 후보"를 잘라준다.
  기계는 있고 그것을 쓰는 어휘가 없었다.
- **`PendingValuation`은 평가에 시계가 없어서 생긴 우회다.** pending 슬롯 하나에
  `AcceptedIntent`와 함께 들어간다. 시장 시계가 생기면 존재 이유가 사라진다.
- **`constraints/evaluation.py`가 두 phase에서 불린다** — callback(project)과 valuation(monitor).
  한 객체의 두 멤버가 서로 다른 시계 위에 산다는 증상이고, M8·M9가 그것을 가른다.
- **`AccountState`는 원장이 아니라 원장의 fold + 발행 대기 버퍼다.** 진짜 원장은 record의 parquet
  테이블이다. 그 어긋남이 `_appends_one_mark`와 세 벌의 불변식을 낳았다.

### M7에서 발견한 것 (2026-09-09)

- **lifecycle 순서는 그대로 두고 함수 경계만 옮길 수 있었다.** MONITORED가 FEEDBACK_PUBLISHED보다
  앞인 것이 옛 코드의 사실이고 설계와도 맞아서, `close`가 monitoring 뒤에 오게 두면 test_time_002가
  손대지 않고 통과한다.
- **`Filled.previous_mark`.** commit 전의 latest_mark를 다음 단계로 넘겨야 한다 — commit 뒤 root에서
  다시 읽지 않는다.
- **stage 이름(`DUE_*`)은 안 바꿨다.** 실패 코드·timing 키에 박혀 있어 별개 결정. `MARKET_ACCRUE`만
  새 체계.

### M6에서 발견한 것 (2026-09-09)

- **평가 전이가 pending을 소비하면 안 된다.** 옛 `prepare_valuation_only`의 `pending_accepted_intent=None`
  한 줄이 남으면 `after: 5m` 결정이 첫 평가에서 사라진다. 시장 시계 점은 pending을 건드리지 않는다.
- **pending 교체 규칙은 그대로 옳다.** 결정 6개가 각각 5분 뒤를 가리키면 마지막 것만 체결된다 —
  AC-1 둘째 테스트가 관찰로 확인.
- **같은 파일에 글자까지 같은 블록이 둘**(`prepare_valuation_only`/`prepare_marked`) — 치환은 함수
  범위를 먼저 자른다. 빈 end 마커는 "끝까지"가 아니다.
- **`test_run_records`가 `EventLoop.run`의 소스 문자열을 읽는다.** 루프 모양을 바꾸면 그 단언도 바꾼다.

### M5에서 발견한 것 (2026-09-09)

- **fold/offset 증명은 "벽시계에서 instant를 만드는" 쪽에만 필요하다.** 체결은 이제 실재하는
  instant를 거르므로 증명이 사라졌다(가을 DST = 두 후보, 봄 DST = 다음 날). agenda 쪽은 만들므로 남는다.
- **`within: 1d` ≠ 옛 `same_day`.** 16:00 → 다음 날 15:30은 23.5h. 정확히 원하면 `12h`.
- **두 마커 사이 슬라이스 편집이 M4의 `RunAgenda`를 지웠다.** ruff F821이 잡았다. 마커 사이에 다른
  것이 없는지 먼저 센다.

### M4에서 발견한 것 (2026-09-09)

- **기계 sweep은 중첩 `at=`을 훔친다.** 첫 판이 `RunFill(at=...)`의 `at`을 agenda로 옮기고 fill에서
  지웠다. 호출의 자기 들여쓰기 층에서만 보게 고쳤고, diff의 지워진 줄에 `fill`/`trade_price`/`selector`가
  0인지로 감사한다.
- **테스트 픽스처 셋이 "날짜 목록"에 기대고 있었다** (`test_check`, `test_check_collects`,
  `test_preflight`). 날짜가 데이터에서 오자 placeholder 디렉터리가 진짜 parquet이 되어야 했다.
- **UTC 격자를 KST 날짜로 접으면 하루가 는다.** 격자는 venue zone으로 만든다.
- **`1M`은 첫 거래일이다.** `last`는 설계에 없어서 안 넣었다.

### M3에서 발견한 것 (2026-09-09)

- **`plan_orders`는 `positions ∪ targets`를 돈다.** target에서 빠진 보유 종목은 청산 주문이 될 수
  있다. 그래서 runtime 게이트는 target만이 아니라 보유까지 검사한다 — 정상 경로에선 보유가 이미
  선언돼 있으므로 roster가 줄어든 경우에만 걸린다.
- **계획은 첫 미등록에서 멈춘다.** `ExchangeRulesView._declared`가 raise한다. "전부 모아서"는 계획
  **앞**에서만 가능하다.
- **zero-dealt 행은 `kind`를 안 찍는다** (`no_trade`, `dealt_quantity: 0`). roster가 선언한 종목도
  그렇다. M11(`LedgerEntry` 한 모양)에서 origin·detail과 함께 정할 것.
- **judgment 코드는 judgments 모듈에 문자 그대로 철자돼야 한다** (`test_check`의 정규식 대조).
  `flow/roster.py`에서 import하면 "published but not spelled". 두 곳에 철자하고 테스트로 묶었다.
- **roster 없이 돌던 테스트가 34개 파일이었다.** 대부분 `_workspace_for_run`·`_setup`·sample 같은
  공용 픽스처 7곳에 roster를 넣는 것으로 닫혔다. 손으로 `StrategyEventLoop`를 만드는 8곳 중 실제로
  주문하는 것은 `test_time_002` 하나뿐이었다(나머지는 Hold).

### M2에서 발견한 것 (2026-09-09)

- **record의 모든 행이 run identity를 싣는다.** `writes`를 `FrozenRun.identity`에 접자 showcase
  6개의 테이블 52개가 전부 digest에서 움직였다 — 행·열은 같고 `run_id` 열만. identity에 무엇을
  더 접는 마일스톤(M4·M5)마다 되풀이된다. "테이블은 그대로여야 한다"는 게이트 문장은 "행·열이 같고
  `run_id`만 다르다"로 읽어야 한다.
- **showcase digest와 스위트는 같은 `outputs/`를 쓴다.** 동시에 돌리면 파일이 사라졌다 나타난다.
  digest는 스위트가 끝난 뒤에.
- **하위호환 로더의 "접힘".** 옛 `datamodels:` 매핑에서 `dataset_id`를 hoist하면서 매핑을 그 한
  엔트리로 바꿔 써 둘째 멤버가 조용히 사라졌다. 멤버 둘짜리 문서로만 잡힌다 (기록 `202`).
- **shipped skill의 `.md`는 LF.** Windows `write_text`는 CRLF를 만들고 계약 테스트 7개가 떨어진다.

### M0에서 측정한 것 (2026-09-09)

- **record는 재생성 가능하다. 예외가 정확히 둘이고 둘 다 내용이 아니다.** `show_005`를 두 번 돌려
  비교하면 모든 parquet 테이블과 `run.json`이 **바이트 동일**하고, `strategy.json`만
  `.timing.*`(벽시계)와 `.component.path`(절대 경로)에서 갈린다. 기준선은 그 둘만 정규화하면
  성립한다 — 그것이 `scripts/showcase_record_digest.py`가 하는 일이다.
- **showcase 8개 중 6개만 run record를 남긴다.** `show_001`(등록)과 `show_009`(저작 계약)는
  시뮬레이션을 돌지 않는다. 기준선 81 entries의 분포는
  002:5 · 004:2 · 005:12 · 006:20 · 007:12 · 008:30.
- **showcase 8개 병렬 실행은 10~17초다.** `tests/showcases/test_every_showcase_completes.py`
  docstring이 "each takes about forty seconds"라고 적고 있는데 더 이상 사실이 아니다. 캠페인 중
  회귀 비교를 자주 돌려도 싸다.

### M0에서 발견한 환경 문제 둘 (이 캠페인과 무관, 고치지 않았다)

- **`ruff check src/`의 82건은 버전 드리프트가 아니라 회귀였다. 닫았다** (`380ca92b`).
  거의 전부가 `docs/issues/archive/NNN`을 담고 있었다 — 커밋 `6cb3f254`("Archive the 86 closed
  issues and rewrite every citation")가 인용 경로에 `archive/` 8글자를 넣으면서 넘겼고, 길이
  분포가 101~106에 몰린 것이 그 지문이다. **그 커밋이 선언된 lint 게이트를 안 돌렸다.**
  산문과 주석만 재배치했고 코드는 안 움직였다. 기계로 검증: 39개 파일 전부 **문자열의 공백만
  정규화하면 AST가 동일**하고 주석의 토큰열도 동일하다. `develop`으로 cherry-pick 가능하다
  (회귀를 만든 곳이 거기다).
- **`uv run pytest` · `uv run pyright` 콘솔 shim이 깨져 있다** (`uv trampoline failed to
  canonicalize script path`). `uv run python -m pytest` · `uv run python -m pyright`는 정상.
  매니페스트의 명령 문자열이 이 머신에서 그대로는 안 돈다.

## Decision log

| 결정 | 근거 |
|---|---|
| 시계는 둘. 전략 시계는 execution table에서 유도하지 않는다 | 장 마감 후 데이터를 못 쓴다(한 칸 낭비) + 격자 공유 시 느린 전략이 비용을 문다. 설계 §3.2 |
| 날짜는 유도하고 시각은 유도하지 않는다 | 밀도를 바꿔도 거래일 집합은 같다. `UC-TIME-002`의 보장이 유지된다. 설계 §3.3 |
| `writes` 필수, 이름만 | 스키마는 소비자가 이미 선언한다. 이름을 돌리기 전에 짓게 되므로 재실행 문제가 발생하지 않는다. 설계 §2.1-2.2 |
| run은 전략 하나 | 얼린 층 공유는 결정성이 이미 보장한다. 그래프 수준 병렬화가 더 낫다. 설계 §2.3 |
| `Constraint`는 확장점이 아니다 | best effort는 재량이고 재량은 전략의 것이다. 프레임워크가 보장할 것이 없다. 설계 §7.1 |
| Compliance는 전략의 값을 물려받지 않는다 | 감시자가 감시 대상의 목표를 물려받으면 자기채점이다(§7.1의 "두 채점이 갈린다"). 설계 §7.2 |
| Exchange 내부 단계를 고정하지 않는다 | 선물·중국 A주 T+1·채권·옵션이 주문→체결 밖의 일을 한다. 단계를 고정하면 담을 수 없는 venue가 생긴다. 설계 §6.1 |
| 원장 항목은 한 모양 + 출처 태그 | 세 타입의 분류 기준("무엇이 변하나")은 통장이 이미 아는 것이다. 설계 §5.2 |
| Accrual은 자리만 | MVP 밖. 배선만 확정하고 구현은 다음 |
| 측정(구조 분류·성능 벤치)을 하지 않는다 | 소유자 결정 2026-09-09. 결정한 구조대로 착수한다 |
| 패키지 이름은 M14에서 정한다 | 무엇을 하는지가 끝난 뒤에 이름을 정한다(아키텍처 §10) |
| 배선표는 데이터, 타입은 부품/도구 하나만 (M13) | 표는 비교·나열·집계되는 것이고, 코드가 강제할 구조적 사실은 "자기 시계를 선언하는가" 하나다. 설계 §10.2 |
| `flow/run/` — 두 kind를 한 패키지에, 시계로 배열 (M14) | kind는 같은 것을 두 번 본 것이고 남은 차이는 시계 수다. `engine/`(걸음)과는 바뀌는 이유가 다르다. 설계 §10.1 |
| `Role`은 `ComponentKind`를 흡수하지 않는다 (M14) | 등록 가능한 넷과 행 다섯은 다른 집합이다. 합치면 `Role.ACCRUAL`이 없는 문의 값이 된다 |

## Validation

```text
매 마일스톤   uv run pytest tests/ -q -m ""        # test_all
              uv run ruff check src/
              uv run pyright
M6 · M7 · M11 · M12   M0 기준선 record 와 회귀 비교
M8 · M10              showcase 8/8 + shipped skills · scaffold 갱신
M14                   test_the_layers_hold (OPEN 비어 있음) + public.py export 고정
릴리스 전             uv run python scripts/record_shipped_skills.py --check
```

`tests/`는 `src/`를 1:1 미러한다. 어느 한쪽에만 있는 디렉터리는 그 자체로 질문이다.

**이 머신에서는 `uv run pytest`/`uv run pyright` 대신 `uv run python -m pytest`/`-m pyright`를
쓴다** (Discoveries의 환경 문제 참조).

### 기록

| 시각 | 무엇 | 결과 |
|---|---|---|
| 2026-09-09 M0 | `python -m pytest tests/ -q -m ""` | **1614 passed**, 271s |
| 2026-09-09 M0 | `python -m pyright` | **0 errors** |
| 2026-09-09 M0 | `ruff check src/` | **82 findings, 전부 사전 존재** (Discoveries) |
| 2026-09-09 M0 | `showcase_record_digest.py --check` | **81/81 일치** (정리 후 재실행) |
| 2026-09-09 M1 | `python -m pytest tests/ -q -m ""` | **1607 passed**, 189s |
| 2026-09-09 M1 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-09 M1 | `showcase_record_digest.py --check` | **81/81 일치** — record는 안 바뀌었다 |
| 2026-09-09 M8+M9 | `python -m pytest tests/ -q -m ""` | **1643 passed**, 208s |
| 2026-09-09 M8+M9 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-09 M8+M9 | `showcase_record_digest.py --check` | **16/81 이동 → 재기록 → 83/83** |
| 2026-09-09 M10 | `python -m pytest tests/ -q -m ""` | **1652 passed**, 209s |
| 2026-09-09 M10 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-09 M10 | `showcase_record_digest.py --check` | **14/83 이동 → 재기록 → 83/83** |
| 2026-09-10 M11 | `python -m pytest tests/ -q -m ""` | **1654 passed**, 213s |
| 2026-09-10 M11 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-10 M11 | `showcase_record_digest.py --check` | **83/83 일치 — 재기록 없이** |
| 2026-09-10 M12 | `python -m pytest tests/ -q -m ""` | **1654 passed**, 204s |
| 2026-09-10 M12 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-10 M12 | `showcase_record_digest.py --check` | **83/83 일치 — 재기록 없이** |
| 2026-09-10 M13 | `python -m pytest tests/ -q -m ""` | **1660 passed**, 207s |
| 2026-09-10 M13 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-10 M13 | `showcase_record_digest.py --check` | **83/83 일치 — 재기록 없이** |
| 2026-09-10 M14 | `python -m pytest tests/ -q -m ""` | **1660 passed**, 213s |
| 2026-09-10 M14 | `ruff check src/` · `python -m pyright` | **clean · 0 errors** |
| 2026-09-10 M14 | `showcase_record_digest.py --check` | **83/83 일치 — 재기록 없이** |
| 2026-09-10 M14 | `test_the_layers_hold` | **통과 — `OPEN = {}`, `flow.run` 65** |

## Risks and recovery

| 위험 | 완화 |
|---|---|
| **M6이 척추를 바꾼다.** 일별 격자에서 결과가 달라지면 회귀 | M0의 기준선과 바이트 단위 비교. 다르면 되돌리고 원인을 Discoveries에 |
| **M8이 사용자 계약을 깬다.** `Constraint`를 쓰던 코드 전부 | major 경계. scaffold·shipped skills·showcase를 같은 마일스톤에서 갱신. 마이그레이션 노트를 릴리스 문서에 |
| **M4의 전개가 크다.** 97,500 occurrence의 메모리·시간 | 전개 결과를 artifact로 두고 identity만 얼리는 경로를 M4에서 확보. 인메모리가 감당 안 되면 그때 분할 |
| **M6이 촘촘한 격자에서 평가를 훨씬 자주 돌린다** | 의도된 동작이다(설계 §5, 비교 가능성을 위해 손잡이를 없앴다). 감당이 안 되면 그 결정을 다시 여는 것이지 M6을 되돌리는 것이 아니다 |
| **M11·M12가 두 번째 척추 변경** | M8·M9·M10을 사이에 넣어 척추 변경 둘이 연속되지 않게 했다. 각각 독립 회귀 비교 |
| **레이어 순환이 재발** | `OPEN`은 비어 있고 비어 있어야 한다. 한 마일스톤이 간선을 열면 같은 커밋에서 닫는다 |

## Next action

**없음 — 캠페인 완료 (2026-09-10, records `201`-`214`).** 이 계획은 `.agent/plans/completed/`로 옮겨졌다.

캠페인 뒤에 남는 별도 작업(이 계획의 범위 밖, `214` "캠페인 끝"):

1. 설계 §8이 PRD·아키텍처에 흡수된다 — M0가 꽂은 포인터(PRD 6곳 · 아키텍처 3곳)가 입구, 아키텍처 §3.2·§10
   트리(record `188` 시점)가 대상.
2. 설계 §10.3(`writes` 하나 vs 리스트)은 열려 있다.
3. 릴리스 전 `uv run python scripts/record_shipped_skills.py --check`; major 경계(`Constraint` → `Compliance`,
   `strategies:` → `strategy:`, agenda·fill 어휘)의 마이그레이션 노트.
