# qlibx PRD Critical Review

## 1. Review scope

이 리뷰는 qlibx의 목적을 부정하지 않는다. 다음 다섯 가지 방향은 제품의 정체성으로 유지할 가치가
있다고 본다.

- Qlib을 order, fill, position, account lifecycle의 실행 기반으로 사용한다.
- 성공한 결과뿐 아니라 실패와 이미 탐색한 범위까지 reusable evidence로 남긴다.
- Stored artifact를 module 사이의 public integration point로 사용한다.
- Built-in으로 공통 vocabulary를 제공하면서 project-local extension을 허용한다.
- Signed alpha research와 long-only enhanced index implementation을 하나의 lineage로 연결한다.

검토 기준은 “기능이 많거나 적은가”가 아니라, 이 철학을 실제 제품으로 만들 때 PRD가 다음 질문에
충분히 답하는가이다.

1. 서로 충돌하지 않는가?
2. 경제적·시간적·회계적 의미가 하나로 해석되는가?
3. 구현자가 임의의 해석을 추가하지 않고 만들 수 있는가?
4. Acceptance test가 pass/fail을 판정할 수 있는가?
5. AI coding agent와 병렬 연구가 늘어나도 잘못된 evidence를 더 빨리 생산하지 않는가?

`wrong`은 qlibx의 방향이 틀렸다는 뜻이 아니라, 현재 문장 그대로 동시에 만족할 수 없거나 잘못된
보장을 만들 수 있다는 뜻으로 사용한다.

근거 수준도 구분한다. Matched-capitalization의 direct `Position` mutation처럼 prototype과 Qlib source로
확인한 사항은 `prototype-confirmed`로 명시한다. 그 밖의 항목은 PRD 내부 문장 사이의 충돌 또는 아직
구현 전에 닫아야 할 contract risk이며, 이미 발생한 구현 결함으로 단정하지 않는다.

또한 이 review에 등장하는 field, type, state와 mode 이름은 semantic distinction을 설명하기 위한 예시다.
해당 이름 자체를 mandatory public schema로 고정하자는 제안이 아닌 경우 이를 명시한다.

## 2. Executive assessment

현재 PRD는 product vision과 capability inventory로는 강하다. 특히 data availability, closed-loop
execution, stored evidence, flexible budget, physical holding과 look-through exposure의 분리는 좋은
기준점이다.

그러나 implementable product contract로는 아직 세 종류의 문제가 크다.

- **경계와 일관성의 공백**: Qlib만 account authority라고 하면서 matched-capitalization은 Qlib fill 외부에서
  composite position과 cash를 바꾼다. Deterministic StrategyAgent를 요구하면서 stochastic strategy와
  외부 AI runtime의 재현성은 예외로 둔다. Same-branch 병렬성의 구체적 guarantee는 session/catalog에
  집중되어 있지만, 상위 제품 문장은 user-owned file edit까지 포함하는 것으로 오독될 수 있다.
- **경제적 의미의 빈칸**: signed alpha, active weight, member coefficient, benchmark-relative intent,
  physical target 사이의 unit과 financing invariant가 없다. 각 component가 type-correct한 output을
  만들어도 서로 다른 의미의 숫자를 정상적으로 연결할 수 있다.
- **연구 타당성의 빈칸**: lineage와 nearest-neighbor 검색은 잘 정의되어 있지만, 반복적인 alpha search가
  holdout을 오염시키고 false discovery를 키우는 것을 통제하는 evaluation governance가 없다. 이 상태의
  centralized catalog는 knowledge base인 동시에 selection-bias amplifier가 될 수 있다.

따라서 구현 전에 최소한 다음 네 가지를 PRD-level invariant로 고정해야 한다.

1. `knowledge_time`을 포함하는 bitemporal point-in-time contract
2. signed intent의 unit, NAV, financing과 feasibility contract
3. Qlib composite account와 capitalization state를 함께 다루는 atomic accounting contract
4. deterministic, seeded stochastic, externally stochastic run의 재현성 등급

## 3. Claude review와의 비교 및 fact check

비교 대상은
[`critical-review-on-prd-claude.md`](critical-review-on-prd-claude.md)다. 두 리뷰는 독립적으로 작성되었지만
핵심 진단은 상당 부분 수렴한다. 차이는 결론보다 review lens와 주장 강도에 더 가깝다.
외부 source fact check는 2026-07-24 현재의 Qlib official main/documentation과 인용된 1차 자료를 기준으로
했으며, prototype 근거는 이 repository의 local source path를 함께 남긴다.

### 3.1 공통점

| 공통 쟁점 | Claude review | 이 review | 종합 판단 |
|---|---|---|---|
| Matched-capitalization authority | Endowment와 “두 번째 execution engine 금지”의 양립 설명 부족 | Qlib account authority와 direct state mutation 충돌 | 최우선 경계 문제다. Mechanism을 폐기할 이유는 없지만 market fill과 account administration authority를 분리해야 한다. |
| StrategyAgent reproducibility | Determinism 감사 절차 부재 | Deterministic/stochastic requirement 자체의 모순 | 재현성 등급과 replay audit를 함께 추가해야 한다. |
| Resource bound | Nested child/parallel agent의 depth와 총량 제한 부재 | Local extension/agent의 resource limit과 cancellation 부재 | Request-local limit뿐 아니라 run/session/project quota가 필요하다. |
| Catalog lifecycle | Retention/archival 부재 | Retention, GC, export/import 부재 | Evidence 보존과 payload retention을 분리해야 한다. |
| Research decision lifecycle | Promotion state machine 제안 | Attempt/artifact/decision state 분리 | Claude의 promotion vocabulary를 더 일반적인 세 state machine으로 흡수하는 것이 낫다. |
| Execution economics | Cost/capacity/reserve 진단 부족 | Unit/financing/metric semantics 부족 | Cost model, capital usage와 capacity를 versioned input/artifact로 승격해야 한다. |

### 3.2 Claude review가 더 잘 포착한 부분

다음 항목은 원래 Codex review에 없거나 충분히 구체적이지 않았다.

- Cost model의 point-in-time definition, version과 lineage
- Predicted tracking risk와 realized tracking diagnostic의 구분
- qlibx schema/catalog migration 및 supported Qlib version range
- Benchmark membership/weight의 announcement time과 effective time
- Matched-capitalization path와 enhanced-index path의 관계
- Baseline reserve가 만드는 capital usage와 capacity opportunity cost
- Fixed-budget default가 적용되었다는 explicit provenance
- Orthogonality metric 중 scale-sensitive metric의 normalization

이 항목들은 아래 finding에 반영한다. 다만 risk model과 correlation에 관한 원문의 주장 강도는 fact
check 결과에 따라 조정한다.

### 3.3 Codex review가 더 잘 포착한 부분

반대로 다음 항목은 Claude review보다 이 review가 더 강하게 다룬다.

- Signed score부터 physical target까지 unit, reference NAV와 financing invariant
- Revision/vintage를 포함하는 bitemporal data contract
- Same-branch guarantee를 qlibx-owned state로 한정해야 하는 product boundary
- Holdout consumption, multiple search와 false-discovery governance
- Frozen executable environment와 local source/data content identity
- Strategy output kind별 capability와 typed composition
- Stored-alpha member 사이의 decision clock/staleness compatibility
- Portable artifact와 environment-bound checkpoint의 구분
- Local extension의 trusted-code, permission와 secret boundary
- Acceptance criterion의 testability와 release sequencing

두 목록은 대체 관계가 아니다. Claude review는 cost, enhanced-index risk, version compatibility와 실제
운영 economics에 더 집중했고, Codex review는 semantic invariant, epistemic validity, artifact boundary와
agent trust model에 더 집중했다.

### 3.4 Fact check 1 — Matched-capitalization은 실제로 두 번째 execution engine인가?

**판정: Claude의 “PRD 설명 부족”이 더 정확하고, 기존 Codex review의 “두 execution path가 존재한다”는
관찰은 맞지만 “두 번째 execution engine”이라고 단정하면 과하다.**

Qlib 공식 source에서 정상 market execution은 `Exchange.deal_order()`가 tradability와 dealt amount를
결정한 뒤 `Account.update_order()` 또는 `Position.update_order()`를 호출한다
([Qlib `exchange.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py),
[Qlib `account.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/account.py)).
`Position.update_order()` 자체는 이미 계산된 trade result로 position을 바꾸는 low-level mutation이다
([Qlib `position.py`](https://github.com/microsoft/qlib/blob/main/qlib/backtest/position.py)).

현재 prototype의 capitalization은 실제로 `Exchange.deal_order()`와 `Account.update_order()`를 거치지
않고 `account.current_position.update_order()`를 직접 호출한다
([prototype `backend.py`](../../qlib-integration-codex/kwam_qlib_backend/backend.py#L1059-L1112)).
따라서 이것은 Qlib market fill이 아니며 Qlib의 turnover/cost indicator update path도 자동으로 타지
않는다.

그러나 별도의 독립 account에서 가상 fill을 advance하는 것은 아니다. 같은 Qlib `Position`에 대한
account administration event다. 올바른 결론은 다음이다.

- “Qlib dealt fill만 realized market execution이다”는 원칙은 유지할 수 있다.
- “Qlib lifecycle 외에는 account state를 바꾸지 않는다”는 더 강한 문장은 유지할 수 없다.
- Capitalization을 명시적 non-market administration event로 정의하고 joint checkpoint, event log,
  accounting reconciliation을 요구해야 한다.

따라서 아래 finding의 `[WRONG AS WRITTEN]`은 mechanism이 틀렸다는 뜻이 아니라 **authority 문장이 현재 형태로
틀렸다는 뜻**으로 좁혀 읽어야 한다.

### 3.5 Fact check 2 — Enhanced index에는 risk model이 반드시 필요한가?

**판정: Claude review의 문제의식은 맞지만 “risk model이 필수”라는 결론은 너무 강하다.**

Ex-ante tracking error를 covariance 방식으로 예측하거나 optimizer constraint로 사용하려면 covariance
matrix 또는 factor risk model이 필요하다. MSCI의 active-risk formulation도 active weight와 covariance
matrix를 사용하고, S&P의 mean-tracking-error 사례 역시 covariance matrix를 사용한다
([MSCI, *Declining Active Risk*](https://www.msci.com/documents/10199/2c6649a3-e9de-4170-9bf7-3eb364264808),
[S&P DJI mean-tracking-error example](https://www.spglobal.com/spdji/en/documents/education/education-improving-the-60-40-policy-benchmark-diversifying-within-equity-allocations.pdf)).

하지만 enhanced index construction 자체가 risk-model-based일 필요는 없다. S&P DJI는 explicit
constraint를 사용하는 “glass-box optimization”과 risk-model optimization을 비교하고, 전자도 realized
tracking error를 측정할 수 있음을 보여준다
([S&P DJI glass-box optimization](https://www.spglobal.com/spdji/en/research/article/etfs-in-asset-owner-portfolios/)).

따라서 PRD에 필요한 것은 mandatory risk model이 아니라 다음의 구분이다.

- Ex-ante predicted tracking risk: model/scenario, covariance/factor input, estimation time와 version 필요
- Ex-post realized tracking error: realized active return series와 evaluation window 필요
- Model-free proxy: sector/weight deviation 같은 proxy임을 명시하고 “predicted tracking error”로 부르지 않음

### 3.6 Fact check 3 — Orthogonality correlation은 scale에 취약한가?

**판정: Pearson correlation에 한정하면 Claude review의 표현은 틀리다. 더 넓은 orthogonality metric에
대해서는 문제의식이 맞다.**

Pearson correlation은 covariance를 두 표준편차로 나눈 값이다
([NumPy `corrcoef` 공식 문서](https://numpy.org/doc/stable/reference/generated/numpy.corrcoef.html)).
따라서 한 alpha를 양의 상수로 rescale해도 correlation은 바뀌지 않는다. 음의 scale은 부호를 뒤집지만
이는 단순 scale variation이 아니라 direction reversal로 명시적으로 다룰 수 있다.

반면 Euclidean distance, turnover difference, trade overlap의 notional, marginal PnL, capacity와
concentration metric은 scale과 budget policy에 민감하다. 올바른 보완은 “correlation을 scale-normalize”
하는 것이 아니라 다음을 metric별로 선언하는 것이다.

- scale-invariant인지 scale-sensitive인지
- raw budget을 비교할지 common gross/net budget에 맞춘 counterfactual을 비교할지
- sign-equivalent candidate를 같은 family로 볼지
- raw과 normalized comparison을 모두 보존할지

### 3.7 Fact check 4 — Fixed-budget default는 silent inference 금지와 모순인가?

**판정: 논리적 모순은 아니지만 현재 provenance requirement가 약하다.**

§8.4에 fixed dollar-neutral rescale이 default라고 공개되어 있으므로, default의 존재 자체는 hidden
fallback이 아니다. Operation ID/version과 before/after snapshot이 lineage에 항상 기록된다면 silent
rescale도 아니다. 다만 project 또는 proposal이 아무 선택을 하지 않았을 때 자동 적용되는 default가 raw
signal strength를 지우는 것은 사실이다.

따라서 default를 금지할 필요는 없지만 다음을 요구해야 한다.

- Effective config에 `budget_policy=fixed_dollar_neutral`을 materialize한다.
- Raw pre-budget snapshot과 post-budget weight를 모두 보존한다.
- Result summary에 “default-applied”를 표시한다.
- Research comparison은 raw signal quality와 budgeted portfolio quality를 구분한다.

### 3.8 Fact check 5 — Baseline reserve opportunity cost를 active PnL에서 차감해야 하는가?

**판정: 진단 누락 지적은 맞지만 canonical active PnL에서 자동 차감하면 안 된다.**

Reserve가 다른 투자에 사용되었을 때의 수익은 counterfactual이며 선택한 alternative와 funding policy에
따라 달라진다. 따라서 realized active PnL의 사실 항목이 아니다. 대신 다음을 분리해야 한다.

- 실제 reserve 사용량, peak usage, utilization과 blocked-short capacity
- Reserve cash에 실제로 발생한 interest/carry
- User-defined hurdle rate 또는 passive alternative를 사용한 opportunity-cost scenario
- Active return과 total committed-capital return

이렇게 해야 matched-capitalization의 active signal quality와 capital efficiency를 섞지 않으면서 둘 다
관측할 수 있다.

## 4. Critical findings

### [P0][WRONG AS WRITTEN] Qlib이 유일한 account authority라는 원칙과 matched-capitalization의 state mutation이 충돌한다

관련 섹션: 1.2, 2.2, 2.5, 11.1~11.6, P6

PRD는 Qlib의 dealt quantity가 realized execution의 유일한 source이며 qlibx가 별도 execution engine을
유지해서는 안 된다고 말한다. 그런데 matched-capitalization activation은 exchange fill이 아닌 event로
Qlib composite position과 cash state를 직접 바꾸고, 별도 baseline record도 동시에 바꾼다.

이것은 경제적으로 필요한 compatibility mechanism일 수 있지만, 현재 표현대로라면 account state에는
두 mutation path가 존재한다.

```text
Qlib fill
  -> composite quantity/cash 변경

qlibx capitalization event
  -> composite quantity/cash 변경
  -> baseline quantity/reserve cash 변경
```

따라서 “Qlib이 유일한 authority”는 문자 그대로 성립하지 않는다. 정확한 원칙은 다음에 더 가깝다.

> Market execution의 유일한 authority는 Qlib dealt fill이다. Capitalization은 market execution과
> 구분되는 명시적 account administration event이며, composite account와 baseline sub-account를 하나의
> 원자적 transaction으로 바꾼다.

PRD에는 최소한 다음 불변식이 필요하다.

- Capitalization/top-up/release의 허용 시점과 event ordering
- Qlib checkpoint와 baseline checkpoint의 하나의 joint commit ID
- 두 state 중 하나만 저장된 crash를 복구하거나 무효화하는 규칙
- Dividend, split, delisting, stale price, FX, cash interest가 `B`, `C`, `A`에 미치는 영향
- `active NAV`, `booksize`, `baseline reserve`, `composite NAV`의 정확한 식
- Endowment가 Qlib public lifecycle 안에서 실제로 가능한지 검증하는 feasibility gate

P6의 “NAV-neutral”은 숫자 하나를 비교하는 test로 부족하다. 모든 account administration event 전후에
balance-sheet identity와 다음 decision에서 복원한 `A = C - B`가 함께 유지되는지를 검증해야 한다.

### [P0][MISSING] Signed alpha에서 physical portfolio까지 숫자의 unit과 financing invariant가 없다

관련 섹션: 8.1, 8.4, 10.1~10.4, 11.3

PRD에는 `signal`, `signed active weight`, `member coefficient`, `combined active intent`,
`benchmark constituent exposure`, `physical target`이 등장한다. 하지만 어떤 quantity가 어느 NAV에 대한
weight인지, 서로 더할 수 있는 단위인지가 명시되어 있지 않다.

예를 들어 fixed dollar-neutral alpha의 long 합은 `1`, short 합은 `-1`이다. 이 숫자를 benchmark weight에
그대로 더하면 200% gross active book이 된다. 반대로 flexible budget alpha의 net이 0이 아닐 수 있는데,
이 residual이 cash, passive sleeve 또는 financing requirement 중 무엇으로 귀결되는지도 하나의 식으로
정의되어 있지 않다.

필요한 contract는 적어도 다음을 포함해야 한다.

- `signal`은 dimensionless score이며 portfolio weight와 자동 호환되지 않는다는 구분
- Weight의 denominator: active book NAV, total portfolio NAV 또는 benchmark NAV
- Long/short budget의 scale과 leverage 의미
- Ensemble coefficient를 적용하기 전 member normalization 여부
- Active intent와 benchmark weight를 합칠 때 사용하는 active-risk multiplier
- Long-only projection 후 cash 및 passive sleeve와 합한 total weight invariant
- Lot rounding, blocked trade와 constraint relaxation 후 intended/desired/submitted/filled weight의
  denominator 보존
- Currency와 valuation timestamp

권장하는 최소 invariant는 다음 형태다.

```text
dimensionless alpha score
-> declared alpha-to-active-weight policy
-> active weight on declared reference NAV
-> benchmark + scaled active weight
-> feasible physical target + explicit cash
```

이 경계가 없으면 “stored artifact가 public integration point”라는 장점이 오히려 위험해진다. Schema가
맞지만 경제적 단위가 다른 artifact가 조용히 composition될 수 있기 때문이다.

### [P0][MISSING] Point-in-time contract가 revision과 vintage를 표현하지 못한다

관련 섹션: 6.2, 6.4, 7.3, 15

`observation time + availability lag`만으로는 quarterly fundamental, macro data, index constituent,
economic calendar, correction된 market data를 안전하게 표현할 수 없다. 같은 observation/event에 대해
여러 revision이 존재하고, 과거 시점의 연구자는 그중 당시 공개된 vintage만 볼 수 있기 때문이다.

Revision 또는 사전 공지가 가능한 dataset은 적용 가능한 시간 의미를 분리해야 한다. 모든 dataset이 아래
field를 전부 가져야 한다는 뜻은 아니다. Field name은 semantic distinction을 보여주는 예시이며 mandatory
schema name이 아니다.

- `event_time`: 경제적 사건 또는 측정 대상 시점
- `valid_time`: 값이 대표하는 기간
- `knowledge_time` 또는 `published_at`: 이 version을 알 수 있게 된 시점
- `ingested_at`: qlibx project가 해당 version을 수집한 시점
- 필요한 경우 `superseded_at` 또는 revision sequence

Subscription의 핵심 query도 명시해야 한다.

```text
decision_time 기준으로 knowledge_time <= decision_time인 record 중
각 observation key의 latest-known vintage를 선택
```

Correction을 과거 snapshot에 retroactively 반영할지, 새 dataset snapshot으로만 발행할지도 필요하다.
이 규칙 없이 “no look-ahead” acceptance를 통과해도 revised final value를 과거에 사용한 backtest가 생길
수 있다.

Claude review가 짚은 benchmark는 이 contract가 특히 중요한 specialization이다. Benchmark member와
weight에는 최소 `announced_at`, `effective_from`, `effective_to`가 필요하고, strategy가 announcement부터
미리 반응할 수 있는지 아니면 effective date부터만 target에 반영하는지를 별도 policy로 정해야 한다.
Benchmark를 §10.2의 plain input으로만 두지 말고 다른 logical dataset과 같은 snapshot/availability
rigor에 포함해야 한다.

### [P0][WRONG] Determinism 요구와 stochastic/AI 예외가 같은 acceptance 아래 공존한다

관련 섹션: 7.1, 7.5, P2, 15

7.1은 같은 context, version, state, seed에서 같은 result를 요구하면서 random output이나 embedded LLM을
예외로 둔다. P2는 예외 없이 같은 input, version, state, seed가 같은 result를 만든다고 요구한다.
15장은 provider-specific runtime의 재현성을 qlibx 책임 밖으로 둔다.

세 문장은 동시에 acceptance criterion이 될 수 없다. Run을 최소 세 등급으로 나누는 것이 낫다.

1. **Deterministic**: 동일한 frozen input과 implementation에서 byte-equivalent 또는
   semantics-equivalent result를 요구한다.
2. **Seeded stochastic**: RNG algorithm, library version, seed stream과 parallelism 조건까지 freeze하고
   정해진 tolerance 안의 replay를 요구한다.
3. **Externally stochastic**: provider response, model revision 또는 unavailable external state 때문에
   replay를 보장하지 않는다. Cache reuse와 canonical promotion은 별도 policy를 적용하고 raw request,
   response identity와 non-reproducible flag를 남긴다.

Resume equivalence 역시 위 등급별로 정의해야 한다. 외부 AI strategy까지 uninterrupted run과 동일한
observable result를 요구하면 구현 불가능한 보장이 된다.

### [P0][WEAK] Same-branch parallelism의 보장 범위가 qlibx-owned state로 명시적으로 한정되지 않는다

관련 섹션: 1.2, 2.4, 4.7, 9.7, P4

§2.4는 Git branch, worktree와 merge 관리를 out of scope로 명시하고, §9.7의 구체적 guarantee도 대부분
session workspace, frozen input과 catalog publication에 관한 것이다. 따라서 PRD가 arbitrary project file의
동시 편집까지 안전하다고 직접 주장하는 것은 아니다.

다만 §1.2와 §4.7의 “한 branch에서 병렬 연구”와 “qlibx가 자동으로 처리”라는 넓은 표현은 user-owned
strategy, config 또는 instruction file edit까지 포함하는 것으로 오독될 수 있다. qlibx는 run 의미와
publication을 안전하게 만들 수 있지만, 두 agent가 같은 user-owned file을 동시에 수정하는 문제까지
해결할 수는 없다.

“같은 repository와 branch에서 병렬 연구”를 다음 두 범위로 분리해야 한다.

- **qlibx-owned runtime state**: session isolation, immutable input, atomic publication, duplicate/conflict
  detection을 제품이 보장한다.
- **user-owned source/config edits**: qlibx가 conflict-free를 보장하지 않는다. Run start 이후 edit은
  실행 의미를 바꾸지 않지만, edit 자체의 merge/overwrite는 caller와 repository workflow의 책임이다.

P4의 “최소 세 agent” test도 qlibx-managed state에 한정해야 한다. 그렇지 않으면 acceptance가 qlibx가
통제하지 않는 editor와 Git behavior에 의존한다.

## 5. High-priority findings

### [P1][MISSING] Research catalog에는 evidence가 있지만 evaluation governance가 없다

관련 섹션: 4.4, 9.4~9.6, P4

실패한 trial과 searched parameter range를 보존하는 것은 매우 좋다. 그러나 같은 evaluation period를
여러 agent가 반복해서 보고 candidate를 선택하면 그 기간은 사실상 training data가 된다. “true forward
out-of-sample로 거짓 표시하지 않는다”는 금지 조항만으로는 selection bias를 통제하지 못한다.

PRD에 다음 개념이 필요하다.

- Segment role: train, validation, test, sealed holdout, live forward
- 누가 언제 어떤 segment의 metric을 보았는지에 대한 exposure ledger
- Proposal이 허용받은 search budget과 실제 trial count
- Multiple-testing 또는 false-discovery 진단
- Holdout unlock 조건, reviewer와 unlock 이후 해당 segment의 지위 변경
- Promotion evidence와 exploratory evidence의 구분
- Supersede가 나쁜 결과를 지우는 것이 아니라 historical decision을 보존한다는 규칙

Orthogonality가 높다는 사실은 statistical validity를 대신하지 않는다. qlibx가 “새 연구는 기존
evidence에서 시작한다”는 철학을 진짜로 지키려면, evidence의 존재뿐 아니라 evidence가 얼마나
소비되었는지도 알아야 한다.

§2.3에 따라 concrete evaluation threshold와 promotion decision은 project가 소유해도 된다. qlibx가
소유해야 하는 것은 특정 통계 policy가 아니라, project-selected policy, evidence exposure와 decision
transition을 기록하고 적용할 공통 contract다.

### [P1][MISSING] Enhanced-index execution과 matched-capitalization execution의 route taxonomy가 없다

관련 섹션: 1.1, 1.3, 3.5, 9.3, 10, 11

§1.1은 qlibx capability를 독립적으로 사용할 수 있다고 명시하므로 모든 alpha가 enhanced-index와
matched-capitalization을 차례대로 거쳐야 하는 것은 아니다. 그럼에도 전체 flow는 signed active intent를
long-only enhanced-index portfolio로 변환한 뒤 Qlib에서 실행하고, §11.2는 signed alpha 자체를
matched-capitalization으로 실행하고 audit하는 별도 compatibility mode를 소개한다. 두 경로는 경제적
대상과 accounting denominator가 다르다.

```text
Route A: signed alpha -> enhanced-index constructor -> long-only physical target -> Qlib
Route B: signed alpha -> matched-capitalization composite target -> Qlib
```

Route B가 pure alpha execution diagnostic인지, deployable alternative인지, Route A와 어떤 비교 관계인지
정의되어 있지 않다. 필요한 contract는 다음과 같다.

- 각 route의 product purpose와 allowed input/output
- Alpha run, portfolio run, matched-capitalization run과 backtest run의 identity 관계
- Route A와 B에서 performance denominator, cost와 capital usage가 다른 이유
- 같은 alpha의 두 route 결과를 attribution할 implementation-gap report
- Route B 결과가 long-only enhanced-index promotion evidence를 대체할 수 없는 조건

이 구분이 없으면 “하나의 lineage”가 서로 다른 portfolio semantics를 동일한 backtest variation처럼 보이게
할 수 있다.

### [P1][MISSING] Cost model이 dataset과 같은 급의 versioned input contract가 아니다

관련 섹션: 2.3, 8.1, 9.5, 10.2, 11.1, 12.3

PRD는 cost를 alpha evaluation, marginal contribution, optimizer와 Qlib execution 전반에서 사용하지만,
cost definition의 identity와 time semantics는 “project가 소유한다”는 문장에 머문다. Commission, tax,
spread, slippage, market impact, borrow-related assumption은 서로 다른 source와 적용 시점을 가진다.

Cost contract에는 최소한 다음이 필요하다.

- Cost component와 적용 대상 instrument/side/venue
- Rate, currency, unit, minimum fee와 rounding
- 규제·fee schedule처럼 적용 시점이 있는 component의 announcement/effective-time metadata
- Estimate인지 actual schedule인지와 calibration dataset
- Execution-time cost와 research-time capacity proxy의 구분
- Model ID/version, parameter와 frozen-run identity
- Expected cost, Qlib realized/simulated cost와 post-trade attribution의 구분

Cost가 바뀌면 alpha definition이 반드시 바뀌는 것은 아니지만 cost-aware evaluation, portfolio와 backtest
identity는 달라져야 한다. 이 transitive invalidation rule도 §9.3에 들어가야 한다.

### [P1][MISSING] Enhanced-index의 predicted risk와 realized tracking error가 같은 “tracking diagnostics”로 뭉쳐 있다

관련 섹션: 8.3, 10.2, P5

§10.2의 “tracking diagnostics”가 ex-ante forecast인지 ex-post realized metric인지 불명확하다. Fact check에서
확인했듯 enhanced index가 반드시 factor risk model을 사용할 필요는 없지만, predicted tracking error를
제공하려면 risk estimate가 필요하다.

Portfolio constructor는 다음 mode를 명시적으로 선언해야 한다.

- `risk_model`: covariance/factor risk model로 predicted active risk를 계산
- `scenario`: historical 또는 user-defined scenario distribution으로 predicted risk를 계산
- `constraint_only`: weight/exposure deviation만 통제하고 predicted tracking error는 제공하지 않음

Risk input에는 estimation window, availability time, frequency, annualization, shrinkage/missing policy,
model version과 coverage가 필요하다. Realized tracking error는 이후 backtest return artifact에서 계산하고
predicted value와 별도로 저장해야 한다.

### [P1][WEAK] Frozen run은 config뿐 아니라 executable environment와 data content를 freeze해야 한다

관련 섹션: 4.5, 6.3, 6.6, 9.2~9.3, 12.3

PRD는 config, dataset snapshot, component version과 seed를 고정한다고 하지만, project-local Python
file에는 version이 없을 수 있고 mutable Parquet path는 같은 ID 아래 바뀔 수 있다. Python, Qlib, qlibx,
numerical library, solver와 native dependency 차이도 결과를 바꾼다.

Frozen run identity에 필요한 최소 항목은 다음과 같다.

- Resolved config content digest
- Dataset definition digest와 physical content/snapshot digest
- Local extension source digest와 relevant transitive dependency identity
- qlibx/Qlib/Python 및 결과에 영향을 주는 dependency/solver version
- Calendar, timezone database와 numerical backend
- Seed와 deterministic/stochastic class
- Execution platform에서 결과 의미에 영향을 주는 option

모든 대용량 file을 매번 복사하라는 뜻은 아니다. Immutable snapshot, content-addressed manifest,
versioned external reference 중 어떤 보증을 제공하는지를 artifact에 표시해야 한다.

여기에 compatibility policy도 필요하다. Qlib 공식 changelog도 Strategy/Account/Position/Exchange와
backtest 관련 refactor를 version별로 기록한다
([Qlib changelog](https://qlib.readthedocs.io/en/latest/changelog/changelog.html)). qlibx는 supported Qlib
version range와 tested adapter matrix를 release metadata에 선언하고, 범위 밖에서는 warning으로 계속
실행하지 말고 명시적으로 실패해야 한다.
Catalog와 artifact schema upgrade는 다음 중 하나로 판정되어야 한다.

- 현재 version에서 native read 가능
- Read-only legacy evidence로 사용 가능
- Deterministic migration 후 사용 가능하며 original payload를 보존
- Incompatible/quarantined이며 promotion input으로 사용 불가

Package upgrade가 과거 evidence를 조용히 재해석하거나 보이지 않게 만들면 “새 연구는 기존 evidence에서
시작한다”는 제품 철학이 깨진다.

### [P1][WEAK] StrategyAgent output kind별 decision authority와 downstream capability가 under-specified다

관련 섹션: 7.2, 12.1

Strategy output이 signal, weight, order 또는 “declared payload” 모두일 수 있다는 유연성은 local
extension에는 편리하다. 하지만 이것을 하나의 generic downstream path로 처리하면 alpha transform,
ensemble, optimizer와 execution adapter 중 무엇을 적용해도 되는지 타입만으로 판단하기 어렵다.

최소한 output kind별 capability를 분리해야 한다. 아래 type name은 가능한 taxonomy의 예시이며 mandatory
class/schema 이름이 아니다. PRD가 고정해야 할 것은 이름이 아니라 각 output kind의 decision authority와
allowed downstream operation이다.

- `SignalDecision`: rank/transform/alpha evaluation 가능, 직접 주문 불가
- `ActiveWeightDecision`: budget/ensemble/portfolio construction 가능
- `PhysicalTargetDecision`: optimizer를 이미 통과한 physical intent
- `OrderDecision`: execution policy를 명시적으로 소유하며 Qlib adapter만 소비
- `DiagnosticPayload`: decision authority가 없고 record/report 전용

Parent가 child output을 composition할 때도 output kind와 data/time boundary가 호환되는지 validate해야 한다.
“어떤 payload도 가능”은 extension point가 아니라 validation을 downstream으로 미루는 것이다.

### [P1][MISSING] Stored-alpha ensemble의 temporal compatibility가 정의되지 않았다

관련 섹션: 9.3, 10.1

Ticker alignment만으로 ensemble compatibility가 충분하지 않다. Member가 서로 다른 trading calendar,
timezone, decision clock, rebalance frequency, holding horizon, universe, price convention, availability
policy를 가질 수 있다.

Ensemble contract는 다음을 명시해야 한다.

- 공통 decision grid와 as-of alignment rule
- Slow member의 last observation을 carry할 수 있는 최대 staleness
- Holiday와 missing rebalance 처리
- Point-in-time universe가 다른 member의 absent ticker 의미
- Weight가 effective해지는 시점과 expiry
- 서로 다른 reference NAV와 budget scale의 normalization
- Member artifact가 부분 coverage일 때 coefficient를 renormalize하는지 여부

이 규칙이 없으면 strategy를 다시 실행하지 않는 reuse가 가능하더라도, 과거에 생성된 weight를 미래의
다른 clock에 잘못 붙일 수 있다.

### [P1][WEAK] Portable artifact와 serializer/report deliverable의 compatibility boundary가 under-specified다

관련 섹션: 1.2, 12.3~12.4, P7

12.3은 recordable Python type이나 serializer의 목록을 미리 제한하지 않으면서 payload 의미와 loader가
명확해야 한다고 요구한다. 두 문장은 논리적으로 양립할 수 있다. Custom serializer도 versioned independent
loader와 compatibility contract가 있으면 portable할 수 있기 때문이다.

문제는 현재 문장만으로 arbitrary Python object/pickle 같은 environment-bound payload가 canonical
integration artifact로 승격되는 나쁜 구현을 충분히 배제하지 못한다는 점이다. 따라서 모순이라기보다
portability grade와 allowed downstream use의 under-specification이다.

Artifact payload는 최소한 다음 등급으로 나눠야 한다.

- **Portable canonical**: versioned JSON/Parquet/Arrow 등 독립 loader가 있는 public contract
- **Environment-bound checkpoint**: resume 전용이며 exact environment compatibility가 필요
- **Diagnostic attachment**: canonical integration input으로 사용할 수 없는 opaque payload

12.4는 최종 HTML, image, document를 report output으로 두고 alpha, backtest 또는 ensemble lineage를
구성하는 artifact에서는 제외한다. 이 분리는 타당하며 provenance를 금지하는 문장도 아니다. 다만 최종
deliverable이 어떤 source artifact와 analysis/renderer version에서 생성되었는지를 기록하라는 요구는
명시되어 있지 않다.

최종 report는 `research artifact`가 아닌 `report artifact/deliverable`로 분류하고 source artifact
reference, analysis version, renderer version을 가져야 한다. Catalog의 promotion graph에서는 제외할 수
있지만 artifact provenance까지 버릴 이유는 없다.

### [P1][MISSING] Local extension과 AI agent에 대한 trust, permission, secret boundary가 없다

관련 섹션: 2.3, 4.6, 5, 12.1~12.2, 15

Project-local Python extension은 사실상 arbitrary trusted code다. Dataset, credential, filesystem,
network와 subprocess에 접근할 수 있고 artifact를 위조하거나 frozen boundary 밖의 data를 읽을 수도
있다. “public contract만 사용한다”는 instruction은 security control이 아니다.

PRD는 v1에서 sandbox를 제공하지 않더라도 다음을 명시해야 한다.

- Local extension은 trusted code인지, untrusted code 실행은 out of scope인지
- Agent action의 read/write/execute/network capability와 approval boundary
- Secret이 config/artifact/log에 들어가지 않게 하는 redaction rule
- Artifact producer trust level과 verified status
- External process나 network를 사용한 run의 provenance와 reproducibility downgrade
- Resource limit, cancellation과 runaway child research의 cleanup behavior

Resource limit은 §7.3의 개별 nested request field만으로 충분하지 않다. Product가 강제하는 다음 aggregate
budget이 필요하다.

- Child가 다시 child를 spawn할 수 있다면 maximum depth와 cycle detection, 허용하지 않는다면 explicit fail
- Parent run당 총 child evaluation 수와 concurrent child 수
- Session/project별 CPU, memory, wall time와 artifact byte quota
- 여러 agent 사이의 admission control과 fair scheduling
- Parent cancellation/crash 시 descendant cancellation과 incomplete-state publication rule

이 경계를 명시하지 않으면 “verified artifact”가 schema validation만 통과한 것인지, trusted execution에서
생성된 것인지 구분할 수 없다.

### [P1][WEAK] Acceptance criteria가 capability checklist이며 검증 가능한 release contract는 아니다

관련 섹션: 13 전체

P0~P7은 넓은 capability group이지 priority 또는 release sequence가 아니다. 대부분 “제공한다”,
“사용할 수 있다”, “관측할 수 있다” 수준이라 pass/fail fixture와 허용 tolerance를 만들기 어렵다.
또한 onboarding부터 matched-capitalization, optimizer, parallel catalog, local renderer까지 하나의
undifferentiated acceptance set에 들어 있어 smallest viable product 또는 release slice가 보이지 않는다.

Acceptance criteria에는 다음이 더 필요하다.

- 각 criterion의 canonical test scenario와 expected observable output
- Determinism의 byte equality인지 numerical tolerance인지
- Crash point와 recovery test matrix
- Dataset/portfolio size에 대한 performance envelope
- Maximum memory amplification과 artifact storage behavior
- Schema migration/backward compatibility 기간
- Unsupported input과 degraded result의 명시적 상태
- Release gate와 dependency: 예를 들어 accounting feasibility가 증명되기 전 signed execution을
  supported로 표시하지 않음

`P0`라는 표기는 일반적으로 최고 우선순위로 읽히므로 현재 P0~P7이 priority인지 capability 번호인지도
바꾸거나 정의하는 것이 좋다.

## 6. Medium-priority findings

### [P2][WEAK] Product persona와 authority가 “human”과 “agent” 사이에서 불명확하다

Human journey는 짧은 자연어 요청을 강조하지만 data mapping, holdout unlock, promotion, extension
execution, source/config write는 의미가 큰 결정이다. 어떤 action이 agent가 자율적으로 할 수 있는
reversible operation이고, 어떤 action이 human confirmation을 요구하는지 정의되어 있지 않다.

최소한 `inspect`, `plan`, `materialize`, `execute`, `publish`, `promote`, `unlock evidence`의 authority
matrix가 필요하다. Agent UX의 목표는 질문을 없애는 것이 아니라, 안전한 default와 필요한 질문을
일관되게 만드는 것이어야 한다.

### [P2][MISSING] Canonical metric semantics가 없어 research 간 비교가 불안정하다

Canonical alpha result는 performance, turnover, cost를 포함하지만 annualization calendar, return
frequency, benchmark, currency, cash return, transaction-cost timing, missing date와 delisting return
처리가 정의되어 있지 않다.

Catalog가 nearest empirical neighbor와 marginal contribution을 계산하려면 동일한 metric name이 동일한
계산을 뜻해야 한다. Metric artifact에 formula/version, input frequency, segment, annualization factor,
currency, cost scope와 coverage를 포함해야 한다.

### [P2][WEAK] Orthogonality metric별 scale semantics가 없다

관련 섹션: 8.4, 9.5

Pearson/Spearman correlation 같은 scale-invariant metric에는 단순 양의 rescale이 문제가 되지 않는다.
하지만 holding distance, turnover notional, trade overlap, marginal contribution, concentration과 capacity는
member budget과 reference NAV에 따라 달라진다.

각 orthogonality metric은 다음 metadata를 가져야 한다.

- `scale_invariant` 여부
- Raw exposure와 normalized counterfactual 중 무엇을 비교했는지
- 사용한 gross/net/side budget과 reference NAV
- Sign reversal을 equivalent family로 처리하는지
- Missing coverage 때문에 effective scale이 달라진 경우의 처리

Semantic orthogonality는 scale/sign variation을 family variation으로 식별하고, empirical result는 raw과
common-budget-normalized view를 함께 제공하는 편이 안전하다.

### [P2][WEAK] Fixed-budget default의 적용 사실과 raw signal 보존이 acceptance에 없다

관련 섹션: 8.4, 8.5, P3

Fixed dollar-neutral default 자체는 silent inference와 논리적으로 충돌하지 않는다. 하지만 아무 설정이
없는 proposal에 자동 적용하면서 raw pre-budget signal을 남기지 않으면 signal strength와 portfolio sizing
effect를 분리할 수 없다.

Effective config, artifact lineage와 result summary에 default 적용 사실을 materialize하고, 최소한 raw
signal, pre-budget candidate weight, post-budget weight를 서로 다른 named snapshot으로 보존해야 한다.
P3도 단순히 fixed/flexible mode 지원 여부가 아니라 default provenance와 before/after exposure를
acceptance로 요구해야 한다.

### [P2][MISSING] Matched-capitalization capital efficiency diagnostic이 없다

관련 섹션: 11.3~11.6, P6

Active PnL에서 baseline price movement를 제거하는 것은 signal return을 보기 위한 올바른 분리다. 그러나
baseline reserve가 실제로 얼마의 capital을 점유했고 어떤 short를 막았는지는 별도 경제적 결과다.

Result에는 reserve balance, peak/average utilization, per-name capacity, funding-blocked intent, actual cash
carry와 total committed capital return이 필요하다. User가 hurdle rate나 passive alternative를 제공한
경우에만 opportunity-cost scenario를 추가하고, 이를 canonical realized active PnL과 섞지 않아야 한다.

### [P2][WEAK] Catalog 상태와 decision 상태의 lifecycle이 덜 정의되어 있다

`successful`, `failed`, `invalid`, `incomplete`는 §4.5, §9.2와 P4에, `rejected`, `promoted`, `superseded`는
주로 §9.6과 lineage 요구에 흩어져 있다. 한 목록에 직접 섞여 있는 것은 아니지만, 서로 다른 lifecycle
축이라는 명시적 구분이 없다. 예를 들어 successful run이 rejected alpha일 수 있고, invalid run은
promotion 대상이 아니지만 diagnostic evidence로는 유효할 수 있다.

다음 state machine을 분리하는 편이 낫다.

- Attempt lifecycle: proposed, running, completed, failed, cancelled, invalid
- Artifact verification: pending, verified, corrupt, incompatible, quarantined
- Research decision: exploratory, retained, promoted, rejected, superseded

각 transition의 actor, concurrency-safe stale-update detection과 durable audit history를 요구하면 stale
update와 crash recovery acceptance도 명확해진다. Compare-and-swap version이나 append-only event는 이를
구현하는 예시이지 PRD가 고정할 mechanism은 아니다.

### [P2][WEAK] “Unknown이면 fail”과 partial/degraded capability 사이의 정책이 필요하다

PRD는 silent fallback을 올바르게 금지한다. 동시에 exposure data가 있을 때만 분석하고 ETF constituent가
없으면 opaque instrument로 실행하는 등 합법적인 degraded mode도 허용한다.

Failure, warning, unsupported와 partial result를 구분하는 공통 taxonomy가 필요하다.

- Required semantic이 없어서 결과가 무효인 경우
- Optional diagnostic만 계산할 수 없는 경우
- Execution은 가능하지만 modelled market reality가 제한된 경우
- 일부 ticker/date coverage만 유효한 경우

이 구분이 없으면 component마다 “명확한 실패”를 다르게 해석하여 지나치게 자주 중단하거나, 반대로
중요한 limitation을 warning으로만 낮출 수 있다.

### [P2][MISSING] Retention, garbage collection과 export/import lifecycle이 없다

성공, 실패, invalid, incomplete run과 intermediate snapshot을 모두 보존하고 nested research까지
지원하면 artifact 수와 storage가 빠르게 증가한다. Content deduplication만으로 충분하지 않다.

Canonical evidence, checkpoint, scratch, diagnostic attachment, report deliverable 각각에 retention,
pinning, garbage collection, archive/export/import와 catalog rebuild policy가 필요하다. 특히 failed
trial을 지우지 않는 철학과 개인정보·대용량 storage 삭제 요구가 충돌할 때 어떤 metadata를 남길지도
정해야 한다.

## 7. 서로 겹치지 않는 creative additions 3가지

### 7.1 Evidence budget: holdout을 “기간”이 아니라 소비되는 자산으로 관리한다

관점: **research epistemology**

각 sealed evaluation segment에 evidence budget을 부여하고, agent가 aggregate metric을 볼 때마다 어떤
정보가 공개되었는지를 기록한다. 전체 return series를 본 경우와 pass/fail 한 bit만 본 경우를 다르게
취급할 수 있다. Budget이 소진되면 그 segment는 더 이상 holdout이 아니며 validation으로 자동
강등된다.

이 기능은 단순한 access control이 아니라 “이 결과를 몇 번의 시도 끝에 발견했는가?”를 lineage에
포함시킨다. qlibx의 실패·검색 이력 철학을 통계적 honesty까지 확장한다.

### 7.2 Alpha fragility card: 성과표 옆에 자동 반증 실험을 둔다

관점: **adversarial model risk**

Promotion 후보마다 작은 perturbation battery를 실행해 하나의 fragility card를 만든다.

- availability를 1~2 bar 늦춘다.
- cost와 slippage를 배수로 올린다.
- 상위 기여 종목 또는 특정 regime을 제거한다.
- rebalance clock을 조금 이동한다.
- missingness와 universe membership을 보수적으로 바꾼다.
- model parameter와 neutralization choice를 가까운 값으로 흔든다.
- 알려진 liquidity shock, 급락, index reconstitution과 corporate-action cluster를 standard stress segment로
  replay한다.
- AUM과 participation rate를 단계적으로 올려 capacity curve와 reserve exhaustion point를 계산한다.

목표는 최악의 경우를 정답으로 삼는 것이 아니라, alpha가 어떤 가정에 brittle한지 구조적으로 보여주는
것이다. Claude review가 제안한 regime/stress replay와 capacity diagnostic은 이 card 안에서 각각 tail
robustness와 execution scalability panel로 들어갈 수 있다. Orthogonality와는 다른 축이며, “새로운가?”가
아니라 “쉽게 깨지는가, 어느 규모까지 버티는가?”에 답한다.

### 7.3 Research portfolio scheduler: compute가 아니라 information gain을 budget한다

관점: **research operations and human attention**

여러 agent가 제안한 trial을 FIFO로 실행하지 않고, 예상 information gain, 기존 evidence와의 중복,
compute/storage cost, human review cost와 unblock할 downstream decision을 기준으로 queue한다. 실행 중간
결과가 stopping condition을 만족하면 남은 child search를 취소하고 budget을 다른 proposal로 옮긴다.
Scheduler는 child depth/count와 session/project quota를 admission control에 사용하고, budget을 초과한
proposal을 단순 failure가 아니라 `deferred-resource-limit` 상태로 남긴다.

이 기능은 strategy나 optimizer가 아니라 research operation layer다. 같은 branch에서 병렬 실행하는
능력을 “더 많은 trial”이 아니라 “더 가치 있는 다음 질문”으로 연결한다.

## 8. PRD에 바로 반영할 우선 수정 목록

1. 1.2와 11장에 market execution authority와 account administration authority를 구분한다.
2. 6.2와 6.4에 bitemporal/vintage schema와 as-of selection rule을 추가한다.
3. Benchmark member/weight에 announcement/effective time을 적용하고 logical dataset snapshot으로 관리한다.
4. 7.1, P2, 15장의 determinism 문장을 reproducibility grade로 통일하고 replay audit를 추가한다.
5. 8~11장에 signal/weight/active intent/physical target의 unit, reference NAV, currency와 financing
   invariant를 추가한다.
6. Cost model을 point-in-time, versioned, transitive identity를 가진 input contract로 승격한다.
7. Enhanced-index risk mode를 `risk_model`/`scenario`/`constraint_only`로 구분하고 predicted와 realized
   tracking error를 분리한다.
8. Enhanced-index route와 matched-capitalization route의 목적, identity와 비교 contract를 추가한다.
9. 9.7의 same-branch 보장을 qlibx-owned state로 한정하고 user-owned file conflict를 명시한다.
10. 9장에 segment role, search budget, evidence exposure와 holdout unlock policy를 추가한다.
11. 10.1에 ensemble member의 calendar/clock/staleness/budget compatibility를 추가한다.
12. qlibx/Qlib support matrix와 catalog/artifact schema migration state를 추가한다.
13. 12.3에 portable/checkpoint/diagnostic compatibility grade와 grade별 downstream usage를 추가한다.
14. 12.4의 report를 non-canonical `report artifact`로 정의해 provenance를 유지한다.
15. Local extension의 trusted-code boundary, secret redaction, depth/count/project-level resource quota와
    cancellation policy를 추가한다.
16. Run, artifact verification, research decision state machine을 분리한다.
17. P0~P7을 capability 번호로 명명하거나 실제 release priority와 test scenario로 다시 작성한다.

## 9. Final assessment

qlibx PRD의 가장 큰 강점은 alpha formula library가 아니라 **time-bounded research, reusable evidence,
closed-loop execution과 physical implementation을 한 product language로 묶으려는 시도**다. 그만큼 가장
큰 위험도 기능 누락보다 semantic ambiguity다.

현재 문서에서 먼저 보강해야 할 것은 더 많은 transform, optimizer 또는 agent command가 아니다.
`언제 알았는가`, `이 숫자의 단위는 무엇인가`, `누가 state를 바꿀 권한이 있는가`, `같은 run이 무엇을
뜻하는가`, `이 evidence를 이미 얼마나 소비했는가`를 public contract로 고정하는 일이다.

이 다섯 질문이 명확해지면 나머지 capability는 독립 module로 확장하기 쉽다. 반대로 이 질문이 열린
상태에서 broad acceptance를 구현하면, qlibx는 많은 artifact를 재사용할 수는 있어도 그 artifact가
같은 경제적·시간적 의미를 가진다는 보장은 하기 어렵다.
