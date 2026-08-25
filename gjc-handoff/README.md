# START HERE — vqapr agent-first surface, 다음 세션 브리프

작성: 2026-08-25 15:25 KST. 세션 3(`01a03479-6572-71ee-a423-897459b75deb`)이 종료되면서 남긴
인수인계다. **다음 세션은 이 repo(`qlibx`)를 working directory로 열고 이 문서부터 읽는다.**

세션 1~3은 sibling repo `kwam-enhanced-index`를 root로 열었고, 그래서 qlibx 작업이 계속
cross-repo로 돌아갔다. 그게 실수였다. 작업의 무게중심은 여기다.

---

## 0. 한 문장

**원래 ultragoal은 죽었다.** 이어받지 말고 `docs/design/agent-first-surface.md`의 설계 결정에서
시작한다. 다만 **factor parity 증명은 살아 있고 기준선으로 남는다.**

---

## 1. 읽는 순서

| # | 파일 | 왜 |
|---|---|---|
| 1 | 이 문서 | 현재 상태, 막힌 지점, 다음 작업 |
| 2 | `docs/design/agent-first-surface.md` (226줄, commit `ad620dd`) | **세션 3의 진짜 산출물.** 원칙 7개와 그 근거 |
| 3 | `gjc-handoff/SESSION-03.md` | 설계 rulings가 나온 경위, 오너 YAML 스키마 |
| 4 | `gjc-handoff/SESSION-02.md` | T2 transactional spine 구현 기록, mutation 검증 |
| 5 | `gjc-handoff/SESSION-01.md` | 최초 세션. **모델 프로파일 사고 기록 포함** |
| 6 | `gjc-handoff/session-01/approved-plan.md` (963줄) | **STALE.** 아래 §3 이유로 대부분 무효 |

측정 증거 원본은 `gjc-handoff/session-03/ledger.jsonl`(114 events, 42 increments)에 있다.
이 문서의 모든 숫자는 거기 또는 이 트리에서 직접 재측정한 값이다.

---

## 2. 현재 상태 (2026-08-25 15:25 KST 재측정)

### qlibx (이 repo)

```
branch   jaepil-develop
HEAD     ad620dd  Record the surface rulings and why Simulation grew to nine fields
tree     clean
tests    uv run --no-sync pytest -q  ->  1036 passed in 127.57s
lint     uv run --no-sync ruff check .  ->  All checks passed
commits  d23ca03..ad620dd = 12개
push     안 함.  tag 없음.  release 없음.
```

### kwam-enhanced-index (sibling, testbed 보유)

```
branch   develop
HEAD     31e6750  Add session 3 handoff: the original plan is stale, start from the design
commits  07c1c6e..31e6750 = 9개 (전부 vqapr-testbed-2 관련)
tests    vqapr-testbed-2 에서 uv run --no-sync pytest -q  ->  56 passed
push     안 함.
```

### 마이그레이션 진척

- **showcase 3/8 완료** — `show_001`, `show_002`, `show_004`
- **legacy 잔존 5개** — `show_003`, `show_005`, `show_006`, `show_007`, `show_008`
- **`vqapr.public`을 import하는 src 파일** (재측정, `git ls-files` 기준):
  - 진짜 legacy 소비자 5개 — `agent/sample/exchange.py`, `agent/sample/journey.py`,
    `cli/register.py`, `cli/run.py`, `extension/scaffold.py`
  - 신 surface 자신 1개 — `project.py` (엔진 타입을 지연 import로 끌어씀)
  - 세션 3이 쓴 bridge 6개 — `constraint`, `registration`, `run`, `schedule`, `strategy`, `venue`
  - 그 밖에 `scripts/evidence_public.py`, 테스트 16개
  - **정정:** SESSION-03.md는 legacy 소비자에 `agent/sample/reversal_5d.py`를 넣었는데,
    지금 그 파일은 이미 `vqapr.authoring` 위에 있다. 그 목록은 낡았다.
- **bridge 7개** — `src/vqapr/_internal/{constraint,pit,registration,run,schedule,strategy,venue}_bridge.py`

---

## 3. 왜 원래 계획을 이어받으면 안 되는가

원래 ultragoal은 "legacy `vqapr.public`을 dogfooding으로 걷어내고 breaking `0.2.0a1`을 낸다"였다.
세션 3 중반에 오너가 기준을 바꿨다.

> 기준은 **AI agent가 잘 쓸 수 있느냐**여야 한다. backend를 만들고 frontend를 붙이는 게 아니라,
> user 관점에서 UI를 먼저 설계하고 그것을 backend에 어떻게 연결할지 고민하는 것이다.

그 결과 세션 3이 만든 것 상당수가 **위치가 틀렸다**는 판정을 받았다. 검증이 틀린 게 아니라
**만든 자리가 틀렸다.**

| 만든 것 | 판정 |
|---|---|
| `_internal/*_bridge.py` 7개 | 남발은 좋은 패턴이 아니다. 3개는 소멸 대상 |
| `factors_authoring.py`의 손으로 쓴 cadence 6군데 | periodic trigger는 공용 모듈 + config여야 한다 |
| `Simulation` 필드 7개 | 등록/실행 분리하면 ~4개 |

따라서:

- `gjc-handoff/session-01/approved-plan.md`의 **T3 dogfooding 절반과 T4(G008) 삭제·릴리스는 무효**다.
  노출할 surface 자체가 재설계 중인데 그 surface를 확정 삭제·릴리스할 수는 없다.
- 그 계획의 **T0/T1/T2와 testbed parity 요구는 유효**하고 이미 달성됐다.

---

## 4. 버려지지 않는 것 — parity 증명

**표면이 바뀌어도 이 숫자들은 기준으로 남는다.** 재설계 후에도 동일하게 재현돼야 한다.

migrated `FactorPortfolio`가 legacy model을 실데이터에서 정확히 재현했다.
2,096 callback days, 4,841 instruments.

| factor | callback_days | formations | membership_rows | Kimchi corr |
|---|---|---|---|---|
| SMB | 2096 | 97 | 173,358 | .971509 |
| HML | 2096 | 97 | 110,919 | .972553 |
| RMW | 2096 | 85 | 93,788 | .941883 |
| CMA | 2096 | 97 | 112,691 | .917683 |
| MOM | 2096 | 102 | 145,568 | .984659 |

- membership은 formation별 instrument set을 diff해서 **name-for-name 동일** 확인 (총계 비교 아님)
- weight는 **636,324개가 decimal for decimal 일치, 차이 0개**
- correlation 5개는 **Project surface만으로 build한 dataset**에서 6자리까지 재현
  (`build_factors_authoring.py` → `compare_factors.py`)

재현 도구: `../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py` (LOCKED dict가 위 표를 들고 있다)

---

## 5. 확정된 설계 (오너 ruling — 재론 금지)

상세는 `docs/design/agent-first-surface.md` 원칙 5~7.

1. **YAML은 선언·등록, Python은 저작·실행.** `DataModel`/`StrategyModel`/(나중에) `Exchange`는
   pluggable module이므로 Python. dataset 등록과 작성한 전략의 설치는 YAML + CLI.
   전략을 쓰는 건 Python, 방금 쓴 전략을 등록하는 건 CLI.
2. **bridge 남발은 smell.** 타입 A를 B로 바꾸려고만 존재한다면 둘 중 하나가 잘못된 자리에 있다.
3. **Exchange friction은 불가피.** 나중에 pluggable로 풀고, 그전까지 `Academic`과 `KRX`는
   **최대한 adjustable**해야 한다. `fractional_allowed`는 "빠진 필드 하나"가 아니라
   adjustability gap이었다.

### 오너가 제시한 YAML 스키마 (아직 설계 문서에 미반영 — 다음 세션의 첫 작업)

`my_strategy_001.py` + `my_strategy_001.yaml`이 짝을 이룬다는 것을 **경로와 함께** 알려주고,
다음을 담는다.

- `DataRequirements`
- **periodic entry trigger** — 모든 전략이 쓰므로 모듈로 만들고 config로 설정
- **weight scheme** — dollar neutral(long 1, short -1) / flexible budget(long ≤1, short ≥-1) / long only
- **recorder table schema** — 어떤 schema의 table로 기록을 남길지

### 이 스키마가 드러낸 gap 2개 (측정 완료, 요구사항으로 박아야 함)

| gap | 위치 | 내용 |
|---|---|---|
| weight scheme 어휘 없음 | `src/vqapr/portfolio/budgets.py:18-22` | `PortfolioDirection`에 `LONG_ONLY`, `SIGNED` **2개뿐**. dollar neutral과 flexible budget이 둘 다 `SIGNED`로 뭉뚱그려져 이름이 없다. `Budget.target_lower`/`target_upper`로 수치는 표현되지만 전략이 "나는 dollar neutral"이라고 **선언할 어휘가 없다** |
| table schema 타입 없음 | `src/vqapr/authoring.py:371-381` | `DiagnosticTable`은 `table_id` + `semantic_fields` **2개뿐**. 필드에 **타입이 없어서** YAML로 table schema를 정할 수 없다 |

### 아직 미확정 질문 하나

**strategy config가 YAML 등록에 들어가나, run 시점에 오나.**
잠정 답은 **run 시점** — `FactorPortfolio` 하나를 5개 factor로 돌리는 게 testbed의 실제 사용
패턴이고, YAML에 config를 넣으면 같은 클래스를 5번 등록해야 한다. 오너 확인 필요.

---

## 6. 왜 `Simulation`이 커졌는가 (측정 결과)

`Project._engine_definition`은 **104줄 중 15줄이 등록 호출**이고, **run마다 등록을 5번** 한다:
`register_execution_input`, `register_agenda`, strategy용 `register_component`, constraint별
`register_component`, exchange용 `register_component`, 그리고 catalog dataset bridge.

즉 `Simulation`은 **한 번 정해지는 것**과 **run마다 달라지는 것**을 같이 들고 있다.

| 등록 시점에 한 번 정해지는 것 | run마다 달라지는 것 |
|---|---|
| execution table 위치와 필드명 | period |
| venue | 시작 account |
| strategy가 어느 클래스인지 | 어떤 constraint가 적용되는지 |
| dataset | 어떤 instrument 위에서 |

`src/vqapr/cli/register.py:98-106`의 `SECTIONS`는 이미 `datasets`, `execution_inputs`, `agendas`,
`components`, `strategy_configs`, `valuation_configs`, `monitoring_policies`를 이해한다 —
**`Simulation`이 재선언하는 것과 정확히 같은 7개.** 선언 경로는 이미 있고 `Simulation`이 복제하고
있다. **새 기계를 만드는 게 아니라 중복을 제거하는 것이다.**

목표 형태:

```python
Simulation(
    period=...,        # when
    account=...,       # from what
    constraints=(...), # under what rules
    instruments=(...), # over what
)
```

**이것이 bridge 대부분을 자동으로 녹인다.** `_engine_definition`이 조립할 게 훨씬 줄기 때문이다.

> 측정 주의: `Simulation`의 현재 dataclass 필드는 `src/vqapr/simulation.py:423-429`에 **7개**다
> (`schedule`, `execution`, `exchange`, `account`, `constraints`, `instruments`,
> `initial_strategy_state`). commit `ad620dd`의 제목은 "nine fields"라고 쓰는데 그 숫자는
> 트리와 맞지 않는다. 인용하기 전에 직접 세라.

---

## 7. 어디서 막혔는가 — 두 번 시도해서 두 번 되돌린 것

**이게 이 문서에서 가장 중요한 절이다.** 같은 벽에 세 번째로 머리를 박지 마라.

### 7.1 `extension/scaffold.py` 마이그레이션 (ledger increment 24, 실패 → revert)

- **왜 중요한가:** scaffold는 모든 신규 저자가 복사해 시작하는 템플릿을 생성한다. 그런데 지금
  그 템플릿이 **이 마이그레이션이 없애려는 바로 그 ceremony를 가르친다** — strategy 템플릿이
  `EconomicPortfolioIntent`를 uuid5로 손수 만들고, `STRATEGY_ID`, window access에서 유도한
  `_source_refs(context)`, `context.account.version`까지 직접 채운다. 저자가 절대 공급하면 안 되는
  framework fact 4개를, 하필 **모범 예제로** 보여주고 있다.
- **막힌 지점:** 두 템플릿을 authoring contract 위로 다시 쓰자 **테스트 10개가 깨졌다.** 되돌렸다.
- **원인:** scaffold는 혼자 마이그레이션할 수 없다. **scaffold + CLI 등록 경로 + loader conformance
  check가 한 단위**다. 셋을 같이 옮겨야 한다.

### 7.2 `agent/sample/{journey,exchange}.py` 마이그레이션 (increment 41, 실패 → revert)

- **왜 골랐나:** dead code가 아니다. `src/vqapr/agent/sample/README.md`가 이것을 reference journey로
  문서화하고 있어서, **agent가 읽고 복사하는 정식 예제**다. 그리고 여기도 ceremony를 가르친다 —
  `reversal_5d.py`가 uuid5 intent id / strategy_id / source_refs / account_version을 손수 만들고,
  `journey.py`가 fingerprint를 직접 계산해 component를 등록한 뒤 agenda 3개 + valuation config +
  monitoring policy를 손으로 붙여 `RunDefinition`을 조립한다.
- **먼저 실baseline을 잡았다:** occurrences 2940, account_version 2929, 10 instruments over 735 sessions.
- **막힌 지점:** **7.1과 똑같은 구조적 커플링**에 걸려 깨끗이 revert.
- **결론:** 개별 소비자를 하나씩 옮기는 방식으로는 이 두 개를 넘을 수 없다. 등록 경로가 먼저
  재설계돼야 한다. 즉 **§5·§6이 §7보다 먼저다.**

### 7.3 showcase 병렬 배치 (increments 16~19, 29 — 두 번 다 revert)

- 1차: 6개 showcase를 병렬 worker로 dispatch. 4개가 "완료"를 보고했지만 **직접 확인하니 4개 전부
  아직 `vqapr.public`을 import**하고 있었다. 게다가 showcase 6개가 각자 `models.py`를 추가하고
  `run.py`에서 bare `import models`를 해서 **sys.path 선점에 따라 다른 모듈이 로드되는 회귀**를
  내가 만들었다. 전량 revert, suite 1020 복구.
- 2차: `show_003`, `show_005`를 fresh baseline과 함께 재투입. 둘 다 green + zero `vqapr.public`으로
  보고됐지만, **입증했다고 주장한 것들을 실제로는 떨어뜨려서** 다시 revert.
- **교훈 셋:**
  1. worker 보고를 믿지 말고 직접 grep/실행해서 확인한다.
  2. slice가 크면 sonnet 워커가 stall한다. **파일 단위로 쪼개면 성공한다.**
  3. 병렬 배치는 공유 이름공간(`models.py`, `sys.path`)을 밟는다. 격리 없이 돌리지 마라.

### 7.4 goal 기계가 G010을 놓지 않았다

`pause` 4회, `drop` 1회 전부 거부됐다 — `"an active story still has resolvable work"`,
`"the aggregate run still has unfinished stories"`. G010이 **성격이 다른 두 반쪽**(완료된 testbed
parity + 미완료 dogfooding)을 한 goal에 묶고 있었던 게 원인이다. 오너가 새 세션 시작을 제안했고
그게 출구였다.

**다음 세션에서 ultragoal을 켠다면 goal 하나에 성격이 다른 두 작업을 묶지 마라.**

---

## 8. 다음 세션의 작업 순서

순서가 중요하다. 아래는 의존 순서이지 선호 순서가 아니다.

1. **설계 문서 확정.** `docs/design/agent-first-surface.md`에 §5의 오너 YAML 스키마를 정식 반영하고,
   gap 2개(weight scheme 어휘, table schema 타입)를 **요구사항으로 박는다.** 미확정 질문
   (strategy config 위치)은 오너에게 확인받는다.
2. **`Simulation` 등록/실행 분리.** §6. `cli/register.py`의 `SECTIONS` 7개가 이미 절반을 이해하므로
   새 기계가 아니라 중복 제거다. `_engine_definition`의 run당 5회 등록이 사라져야 한다.
3. **gap 2개 구현.** `PortfolioDirection`에 dollar neutral / flexible budget 어휘,
   `DiagnosticTable` 필드 타입. 둘 다 YAML 스키마가 표현 가능해지는 전제조건이다.
4. **bridge 정리.** `registration`/`schedule`/`venue`는 **소멸**(등록 시점 선언이 CLI 경로로 이동).
   `strategy`/`constraint`는 adapter가 아니라 **contract implementation**으로 — authoring 타입이
   계약이고 엔진이 그것을 소비한다. `run`/`pit`는 진짜 capability이므로 **자기 이름을 달고 surface에
   남는다.**
5. **cadence를 공용 모듈 + config로.** 지금 손으로 쓴 자리:
   `../kwam-enhanced-index/vqapr-testbed-2/models/factors_authoring.py`의
   `month_index`(:42), `already_formed`(:47), `formed_state`(:59), 그리고 `decide()` 안의
   호출 3군데(:151, :156, :177).
6. **그 다음에야** scaffold + CLI 등록 경로 + loader conformance check를 **한 단위로** 재시도(§7.1),
   이어서 `agent/sample`(§7.2), 이어서 남은 showcase 5개.
7. **각 마이그레이션 후 §4 parity를 재확인한다.** 그게 회귀 탐지기다.

### 삭제가 안전한 이유 (측정 근거)

- `public.py`는 **419줄, 자체 정의 11개**, 28개 모듈에서 re-export하는 얇은 층이다.
  8,139줄짜리 아키텍처 레이어가 아니다.
- **engine 파일 중 이걸 import하는 것은 0개** — `flow/`, `models/`, `portfolio/`, `valuation/`,
  `exchange/`, `data/` 전부 깨끗하다.
- 의존은 한 방향뿐: public → engine. 지워도 engine은 아무것도 모른다.

따라서 **점진적 제거가 가능하다.** dogfooding 하나 끝낼 때마다 legacy 하나씩. 하나 지웠는데
무관한 게 깨지면 그게 멈춰야 할 커플링 신호다. 다만 **설계가 정해진 뒤에** 해야 두 번 안 한다.

---

## 9. 하면 안 되는 것

- **`git push`, tag, publish, release 금지.**
- **`vqapr.public` 삭제 금지.** `0.2.0a1` 금지. 이건 T4/G008이고 **오너의 명시적 승인**이 필요하다.
  삭제는 되돌릴 수 있지만 릴리스는 아니다.
- **`vqapr-testbed-2/baselines/` 건드리지 마라.** §11 참조.
- `git add`/`commit`은 오너가 변경을 확인하고 명시적으로 승인한 뒤에만. (세션 3에서는 오너가
  중간에 commit을 승인해 8단위로 나눠 커밋했다. 기본값은 여전히 금지다.)

---

## 10. 운영 주의사항

- **모델 프로파일은 다음 사용자 턴에 적용된다.** 세션 1이 여기서 사고를 냈다 — 오너가 지정한
  `claude-opus-5` 대신 `gpt-5.6-sol`이 ralplan 전 과정과 ultragoal 실행 전부를 수행했다.
  ultragoal이 무인으로 계속 돌아 턴 경계가 생기지 않았기 때문이다. 상세는 `SESSION-01.md`.
  **새 세션은 처음부터 `~/.gjc/agent/config.yml`의 `modelProfile.default`(= `claude-opus`)를 쓴다.**
  세션을 이어서 할 때만 터미널에 아무 입력이나 한 번 넣어 대기 중인 프로파일을 적용시켜라.
- **worker slice는 파일 단위로 쪼개라.** 큰 slice를 받은 워커가 결과를 저장하지 못하고 stall하는
  일이 반복됐다(`6-BaselineHarness`, `12-AgentFirstModelAdapter`, showcase 배치 전체).
- **워커 보고를 진행 판정으로 쓰지 마라.** 완료된 워커를 오판해 취소한 적이 있고(파일이 3분 전에
  이미 존재했다), "완료" 보고 4건이 전부 목표를 달성하지 못한 적도 있다. **직접 grep하고 직접 실행해라.**
- **capture 프로세스 누수 주의.** 타임아웃된 capture 자식 프로세스 2개가 종료되지 않고 같은 파일에
  계속 써서 디스크 8.8GB를 먹은 적이 있다.

---

## 11. 두 repo의 관계와 경로

```
C:/Users/chlje/DevProjects/
  qlibx/                      <-- 여기서 세션을 연다. vqapr 패키지 본체
    src/vqapr/
    showcases/                    show_001..008
    docs/design/agent-first-surface.md
    gjc-handoff/                  이 문서와 세션 기록
  kwam-enhanced-index/        <-- testbed 소비자 + 세션 durable state
    vqapr-testbed-2/              factor testbed (consumer)
    gjc-handoff/                  SESSION-01/02/03 원본, session-state/
    .gjc/_session-01a03479-.../   세션 3 durable state (gitignored)
```

- `vqapr-testbed-2/pyproject.toml`이 `vqapr = { path = "../../qlibx", editable = true }`로
  **이 트리를 직접 물고 있다.** qlibx를 고치면 publish 없이 다음 testbed 실행에 바로 반영된다.
- **`vqapr-testbed-2/baselines/agent-first-v1/`은 gitignored이고 약 500MB이며 이 머신에만 있다.**
  `materialization.rows.jsonl` 284MB, `publication.rows.jsonl` 223MB, `simulation.trace.jsonl`,
  `declarations.json`, `manifest.json`, `hashes.json`, `performance.json`.
  **이게 모든 parity 증명의 기준점이다. 지우면 §4를 다시 증명할 수 없다.**
  (세션 2가 이걸 잃은 상태로 시작해서 T0 baseline을 통째로 재수립해야 했다.)
- 세션 3의 durable state 사본은 이 repo의 `gjc-handoff/session-03/`에 넣어 뒀다
  (`goals.json`, `ledger.jsonl`, `brief.md`). 원본은
  `../kwam-enhanced-index/.gjc/_session-01a03479-6572-71ee-a423-897459b75deb/ultragoal/`이며
  거긴 gitignored라 언제 사라져도 이상하지 않다.
- 전체 세션 transcript 원본:
  `~/.gjc/agent/sessions/v2-*/2026-08-24T04-14-00-771Z_01a031f9-*/` (세션 1)

### testbed 실행 방법

```powershell
cd C:\Users\chlje\DevProjects\kwam-enhanced-index\vqapr-testbed-2
uv run --no-sync pytest -q                    # 56 passed
uv run --no-sync python parity_probe.py       # 5개 factor locked counts 검증 (오래 걸린다)
uv run --no-sync python build_factors_authoring.py   # Project surface만으로 factor build
uv run --no-sync python compare_factors.py    # Kimchi correlation 재현
```

### qlibx 검증 방법

```powershell
cd C:\Users\chlje\DevProjects\qlibx
uv run --no-sync pytest -q                    # 1036 passed, ~128s
uv run --no-sync ruff check .
```

---

## 12. 이 세션의 결함 9개 — 설계 요구사항의 근거

**전부 표면을 *써보다* 막혀서 나왔고, 읽어서 찾은 건 하나도 없다.** 그래서 이건 버그 목록이 아니라
요구사항이다. 각각은 agent가 말하려다 표면이 표현하지 못한 문장이다.

| agent가 말하려 한 것 | 실제로 일어난 일 |
|---|---|
| "이 dataset을 읽어라" | 등록은 됐는데 `simulate`에서 보이지 않았다 |
| "이 constraint를 적용해라" | constraint를 쓰는 모든 run이 identity에서 실패했다 |
| "이 venue는 소수점 거래를 한다" | 필드가 없었다. 아주 작은 `quantity_step`이 유일한 근사였다 |
| "이 factor를 돌려라" | 생성자 인자를 받는 모델은 아예 만들 수가 없었다 |
| "NAV로 판단해라" | `nav`가 두 bridge 모두에서 `None` 하드코딩이었다 |
| "이 진단값을 기록해라" | schema 검증까지 하고 나서 버렸다 |
| "이 run이 정한 걸 publish해라" | 완료된 run에서 dataset으로 가는 경로가 없었다 |
| "비용을 들여다봐라" | `SimulationSummary`가 정수 4개였다 |
| "내가 쓴 모델을 설치해라" | loader가 자기 패키지가 배포하는 authoring contract를 거부했다 |

이 중 3개는 **표면에 막힌 워커가 우회하지 않고 물어봐서** 드러났다.
**표면에 막힌 agent가 곧 측정값이다.**
