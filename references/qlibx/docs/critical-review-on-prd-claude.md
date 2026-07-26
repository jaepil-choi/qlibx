# qlibx PRD Critical Review (Claude)

> v2: [`critical-review-on-prd-codex.md`](critical-review-on-prd-codex.md)(다른 agent가 같은 `qlibx-prd.md`를
> 대상으로 작성한 독립 리뷰)와 대조하여 공통점·차이점을 정리하고, fact check로 확인된 항목을 반영해 v1을
> 수정한 버전이다. v1의 항목은 그대로 두지 않고 이 개정에 흡수했다.
>
> v3: codex가 이 v2 문서 자체를 다시 검토하고 보낸 반박(수학적 사실 — Pearson correlation의 scale invariance,
> Qlib `Exchange`/`Account`/`Position` 실제 흐름, S&P DJI glass-box optimization 등 외부 근거 포함)을 §2.4에서
> 항목별로 재검증하고 반영한 버전이다. 대부분 정확한 지적이었고, 그 결과 §3.2, §3.4, §3.6, §3.10, §4.1, §4.3,
> §4.4, §5.4의 표현과 등급을 수정했으며, 이 과정에서 codex의 원래 PRD 리뷰 중 내가 v2에서 누락했던 항목
> (evaluation governance, §3.11)도 새로 발견해 추가했다.

## 1. 문서의 지위

이 문서는 [`qlibx-prd.md`](qlibx-prd.md)를 대상으로, qlibx가 스스로 선언한 철학(§1.2: Qlib을 execution engine으로
쓰고 그 주위 research automation만 담당, agent가 public surface만으로 사용, 새 연구는 기존 evidence에서 시작,
built-in은 일관성·local extension은 자율성, stored result가 module 간 유일한 integration point, 한 branch에서
병렬 연구)에 비추어 검토한 기록이다. qlibx의 목적이나 기능 자체(signed alpha, ensemble, enhanced index,
matched-capitalization 등)는 타당하다고 전제하고, 그 목적을 PRD가 실제로 완결되게 뒷받침하는지만 본다.

`docs/critical-review-on-architecture-claude.md`가 이미 architecture 문서와 prototype 증거를 대조한 리뷰이므로,
이 문서는 architecture/구현 수준 diff가 아니라 **PRD 자체의 요구사항 공백·모순**에 집중한다.

**표기 규칙**: 이 문서의 section 번호(§1~§7)와 `qlibx-prd.md`의 section 번호(§1~§15)가 앞부분(§1~§7)에서
서로 겹친다. 문맥상 PRD 원문을 인용/설명하는 곳(예: "§2.2는 '...두 번째 execution engine을 유지해서는 안
된다'고 못박고")은 전부 `qlibx-prd.md`를 가리키고, 이 리뷰 문서 자체의 발견 항목을 다시 참조하는 곳은 "이
문서 §X" 또는 앞뒤 문맥(Missing/Weak/Wrong 목록 번호)으로 구분한다.

## 2. Codex 리뷰와의 비교

### 2.1 수렴한 지점 — 두 리뷰가 독립적으로 같은 결론에 도달

| 주제 | 내 리뷰(v1) | codex 리뷰 | 판단 |
|---|---|---|---|
| Endowment/matched-capitalization이 "두 번째 execution engine 금지"(PRD §2.2) 원칙의 경계를 흐린다(별도 engine이 아니라 같은 Position을 바꾸는 out-of-band mutation) | 이 문서 §4.1(Wrong) | codex PRD 리뷰 §3 [P0][WRONG] 1번 | 서로 다른 근거로 같은 결론. codex는 "market execution authority vs account administration authority" 구분을 제안하며 더 구체적인 불변식(joint checkpoint, crash recovery, corporate action 영향)까지 요구한다. codex는 2차 피드백(이 문서 §2.4의 3번 항목)에서 "두 번째 execution engine"이라는 표현 자체는 부정확하다고 스스로 정정했다 — 별도 account/가상 fill engine이 아니라 같은 Qlib `Position`을 바꾸는 mutation이기 때문이다. **표현은 codex의 정정을 따르되 등급(Wrong)은 유지**한다. |
| Catalog가 무한히 커질 때의 retention/GC 정책 부재 | 이 문서 §2.7(v1 번호, 현재는 §3.10, Missing) | codex PRD 리뷰 §5 [P2][MISSING] "Retention, garbage collection과 export/import" | 동일 결론. codex가 canonical evidence/checkpoint/scratch/diagnostic별로 정책을 나누자는 더 구체적인 제안을 하므로 이를 채택한다. |
| Promotion/decision lifecycle을 명시적 상태로 나눠야 함 | v1 §5.2("creative addition"으로 분류, 현재는 §4.2, Weak) | codex PRD 리뷰 §5 [P2][WEAK] "Catalog 상태와 decision 상태의 lifecycle" (attempt lifecycle / artifact verification / research decision 3분리 제안) | **분류 오류를 인정한다.** 나는 이것을 "있으면 좋은 창의적 제안"으로 분류했지만, codex는 현재 PRD의 상태값(`successful`, `failed`, `rejected`, `promoted`, `superseded` 등)이 실행 상태와 연구 판단을 섞어 쓰는 실제 결함으로 짚었다. PRD 원문(§9.2, §9.6)을 재확인하면 codex 말이 맞다 — 이 상태들은 실제로 한 목록에 섞여 나열되어 있다. 이 항목은 이번 개정에서 **Weak(핵심 결함)으로 승격**하고, creative 목록에서는 제외한다. |
| Benchmark/dataset의 point-in-time 엄밀성 | v1 §2.5(Missing, benchmark rebalance 발표/발효 시차에 한정, 현재는 §3.6에 통합) | codex PRD 리뷰 §3 [P0][MISSING] "Point-in-time contract가 revision과 vintage를 표현하지 못한다" (event_time/valid_time/knowledge_time/ingested_at 4분리, 모든 dataset에 일반화) | 같은 우려의 좁은 사례(나)와 일반 이론(codex). **codex의 일반화가 더 근본적**이므로 이를 상위 항목으로 승격하고, 내 benchmark 사례는 그 구체적 인스턴스로 종속시킨다. |
| Enhanced index 실행 경로와 matched-capitalization 실행 경로의 관계가 불명확함 | v1 §4.2(Wrong, 현재는 §5.5) | codex 2차 피드백 10번: "기존 [이 항목]의 좋은 지적을 더 발전시켜 P0 finding으로 올릴 만합니다" | codex 리뷰(1차)에는 대응 항목이 없었지만, 2차 피드백에서 내 지적을 좋은 finding으로 인정하고 우선순위 격상을 제안했다. §5.5 본문과 §7 우선순위 목록에 반영했다. |

### 2.2 서로 보완하는 지점 — 상충이 아니라 커버리지 차이

내가 다루고 codex가 다루지 않은 것: cost model의 dataset급 point-in-time contract(§3.1), "enhanced index"에
risk method 선언 contract가 없다는 점(§3.2), qlibx 자신의 schema version이 catalog를 무효화할 때의 계약(§3.3),
Qlib 자체 버전 호환/pinning 정책(§3.9), nested child·병렬 agent의 자원/재귀 bound(§3.4), fixed-budget default
rescale의 provenance/observability 약점(§4.4).

codex가 다루고 내가 다루지 않은 것: signal→physical target 사이 unit/NAV/financing invariant 부재(§3.5),
determinism 요구를 등급화해야 한다는 점(내 v1은 "검증 메커니즘 없음"까지만 지적, codex는 §7.1과 P2 acceptance의
문자 그대로의 모순까지 지적, §5.1), same-branch parallelism 보장 범위가 §2.4 out-of-scope와 충돌하는 문제(§5.2),
StrategyAgent output union이 지나치게 열려 있는 문제(§4.5), stored-alpha ensemble의 temporal/calendar
compatibility 부재(§3.7), portable artifact envelope과 unrestricted serializer 허용 사이의 긴장(§5.3), local
extension의 trust/security boundary 부재(§3.8), acceptance criteria(P0~P7)가 capability 목록일 뿐 검증 가능한
release contract가 아니라는 메타 지적(§4.6).

이런 차이는 두 리뷰가 상충하는 것이 아니라 각자 다른 부분을 더 깊게 판 결과다. 아래 3~5장에 codex 쪽 기여를
출처를 밝히고 흡수했다.

### 2.3 Fact check — 실제로 상충되는 주장이 있었는가

결론부터: **두 리뷰가 같은 사실에 대해 정반대 결론을 낸 항목은 없었다.** 다만 아래 두 곳은 codex의 주장을
PRD 원문과 직접 대조해 정확성을 검증할 필요가 있었다.

1. **Determinism 모순 주장 검증** — codex는 §7.1이 "embedded LLM 등 stochastic 예외"를 명시적으로 허용하면서
   §13 P2 acceptance는 "같은 bounded input, version, state와 seed는 같은 StrategyAgent result를 만든다"를
   예외 없이 요구한다고 주장했다. `qlibx-prd.md` 원문을 다시 대조한 결과, §7.1의 괄호 문장("예외 존재. 특수한
   경우...")과 §13 P2 목록의 무조건적 문장이 실제로 나란히 존재하며 서로 조건을 명시적으로 맞춰두지 않았다.
   **codex의 주장은 정확하다.** 이 항목은 내 v1에서 "검증 메커니즘이 없다"는 약한 지적(Weak)에 그쳤으나, 이번
   개정에서 "문장 자체가 조건부/무조건부로 어긋난다"는 더 강한 지적(Wrong)으로 교체한다(§5.1).
2. **Same-branch parallelism 범위 주장 검증** — codex는 §1.2/§9.7이 보장하는 병렬성이 §2.4가 out of scope로
   미룬 "Git branch, worktree 또는 merge 관리"와 실제로는 경계가 겹친다고 주장했다. §9.7 10개 항목을 다시
   읽어보면 전부 "session isolation", "frozen config", "catalog identity/publish 충돌"처럼 **qlibx가 관리하는
   상태**에 대한 보장이고, 두 agent가 같은 로컬 확장 `.py` 파일이나 project config 파일을 동시에 직접 편집하는
   filesystem 수준 경합은 다루지 않는다. **codex의 주장은 정확하다.** 신규 항목으로 채택한다(§5.2).

내 v1에만 있던 항목들(cost model, risk model, Qlib 버전 정책 등)은 codex 리뷰가 반박한 것이 아니라 단순히
다루지 않은 것이므로 그대로 유지했고, 이번 재검토 과정에서 원문과 다시 대조해도 근거가 바뀌지 않았다.

### 2.4 Codex의 2차 피드백(v2에 대한 반박) 재검증

codex가 이 v2 문서를 다시 읽고 10개 항목의 수정 의견을 보냈다. 외부 근거(NumPy 문서, Qlib GitHub 소스, S&P DJI
자료)가 포함된 주장은 원문과 대조해 검증했다(Qlib 소스는 이 저장소의 `.venv`에 설치된 실제 코드로 직접
재확인했고, S&P DJI 링크는 접근 거부로 직접 재확인하지 못했다 — §3.2 참조). 결론: **10개 중 8개(1, 2, 4, 5, 6,
7, 8, 9번)는 정확한 지적이라 본문을 교체하거나 보강했고, 1개(3번)는 결론(등급)은 이미 맞았지만 "두 번째
execution engine"이라는 표현이 부정확해 표현만 정정했으며, 1개(10번)는 지적을 계기로 codex의 원래 PRD 리뷰 중
내가 v1→v2로 옮기며 빠뜨렸던 항목(evaluation governance)을 새로 발견해 §3.11로 추가했다.**

1. **§4.1 orthogonality의 "correlation 왜곡" 주장은 수학적으로 틀렸다 — 반영.** Pearson correlation은
   `corr(cX, Y) = corr(X, Y)` (c>0)로 양의 rescaling에 불변이다(NumPy `corrcoef` 정의와 covariance/표준편차
   공식으로 직접 확인 가능). "budget scale 차이가 correlation 계산을 왜곡한다"는 v2 문장은 부정확했다.
   Correlation 자체가 아니라 holding distance, turnover notional, marginal PnL, concentration, capacity처럼
   scale-sensitive한 다른 metric이 문제라는 codex의 재정식화가 맞다. §4.1을 교체했다.
2. **§3.2 risk model 필요 주장 완화 — 반영.** Enhanced index construction에 covariance/factor risk model이
   반드시 있어야 하는 것은 아니고, explicit constraint만 쓰는 risk-model-free("glass-box") 구성도 실무에서
   쓰인다(S&P DJI 등). "risk model이 빠졌다"보다 "어떤 risk method(`risk_model`/`scenario`/`constraint_only`)를
   썼는지 선언하는 계약이 빠졌다"가 정확하다. §3.2를 교체했다.
3. **§5.4 "두 번째 execution engine" 표현 — 부분 반영(등급은 유지, 표현만 수정).** Qlib 정상 흐름은
   `Exchange.deal_order()`가 tradability/dealt amount를 정하고 `Account`/`Position`을 갱신하는데,
   matched-capitalization은 `Position.update_order()`를 직접 호출해 Exchange fill을 우회한다 — 이 사실관계는
   codex와 architecture review가 이미 코드로 확인한 것과 일치한다. 다만 codex가 정확히 지적했듯 이건 **별도
   account나 독립된 가상 fill engine이 아니라 같은 Qlib `Position`을 바꾸는 non-market administration event**이므로
   "두 번째 execution engine"이라는 표현은 과했다. Wrong 등급(§5.4)은 유지하되 "market execution authority와
   account administration authority를 구분하지 않는다"는 codex의 더 정확한 표현으로 §5.4와 §2.1 표를 수정했다.
4. **§4.3 reserve 기회비용을 canonical PnL 차감처럼 읽히게 쓴 것 — 반영.** Opportunity cost는 counterfactual이라
   대체 투자/hurdle rate 선택에 따라 값이 달라지므로 canonical active PnL에서 자동 차감하면 안 된다는 지적이
   맞다. Reserve balance/utilization, blocked short intent, 실제 interest/carry, user-defined scenario, active
   vs total committed-capital return을 분리하도록 §4.3을 재작성했다.
5. **§4.4 "silent inference 금지 철학과 모순" 표현 — 반영.** PRD가 fixed dollar-neutral rescale을 default로
   공개적으로 명시하고 있으므로 이건 silent inference가 아니라는 지적이 맞다. 실제 문제는 default 적용 여부가
   provenance로 안 남는다는 관측 가능성 문제다. §4.4를 "철학과 모순"에서 "provenance/observability 약점"으로
   재분류했다.
6. **§3.4 재귀가 이미 허용된다고 전제한 것 — 반영.** PRD는 child가 다시 child를 spawn할 수 있는지 자체를
   명시하지 않는데, v2는 "재귀 depth bound가 없다"고 써서 재귀가 이미 가능하다고 전제해버렸다. "허용 여부부터
   불명확하다"로 §3.4를 수정했다.
7. **§3.3/§3.9의 compatibility 구분 — 이미 분리돼 있었음, 세분화만 추가.** codex는 v1(구 버전) 기준 §2.3/§2.6을
   지적했는데, v2에서 이미 qlibx schema/catalog 호환(§3.3)과 Qlib runtime 호환(§3.9)을 별도 항목으로 분리해
   두었다. 다만 "version이 바뀌면 identity가 달라지는 것"과 "과거 evidence 자체가 읽을 수 없게 되는 것"이
   다른 문제라는 세분화는 반영할 가치가 있어 native-readable/read-only legacy/deterministically
   migratable/incompatible-quarantined 4상태 구분을 §3.3에 추가했다.
8. **§3.6 benchmark point-in-time을 구체적 필드로 확장 — 반영.** 일반적인 `event_time`/`valid_time`/
   `knowledge_time`/`ingested_at` 4분리에 더해, benchmark membership에 특화된 `announced_at`/`effective_from`/
   `effective_to`/revision-supersede time과 "발표 이후 선반영 허용 여부" policy를 §3.6에 추가했다.
9. **§3.10 retention에서 metadata/payload 구분 — 반영.** "Evidence를 지우지 않는다"는 원칙이 storage/privacy
   요구와 충돌할 수 있다는 지적이 맞다. Canonical proposal/status/decision/metric summary/lineage(계속
   queryable)와 large payload/checkpoint/scratch/diagnostic attachment(archive/GC 가능, tombstone은 유지)를
   구분하도록 §3.10을 보강했다.
10. **누락 지적 — evaluation governance 항목을 v2에서 빠뜨렸음을 확인, §3.11로 추가.** codex의 원래 PRD 리뷰
    [P1][MISSING] "Research catalog에는 evidence가 있지만 evaluation governance가 없다"는 내가 v1→v2로 옮기며
    누락했다. 반복 alpha search가 holdout을 오염시키고 false discovery를 키우는 문제를 통제하는 계약이 PRD에
    없다는 지적은 정확하므로 새 항목으로 추가했다. 나머지 누락 지적(unit/NAV invariant, bitemporal, same-branch
    범위, ensemble temporal compatibility, portable artifact, extension trust boundary)은 이미 v2 §3.5, §3.6,
    §5.2, §3.7, §5.3, §3.8에 반영되어 있었다. Enhanced-index와 matched-capitalization 실행 경로 구분(§5.5)을
    P0로 올리자는 제안은 §7 우선순위 목록에 반영했다.

## 3. Missing — 철학상 있어야 하는데 없는 것

### 3.1 Cost model에 dataset과 같은 급의 contract가 없다

PRD는 turnover·cost diagnostics(§8.1), cost-aware marginal return(§9.5), enhanced index의 "Cost" input(§10.2),
stock/ETF별 다른 cost(§11.1)를 반복해서 언급하지만, cost 자체가 **어디서 오고 누가 버전을 관리하며 시간에 따라
어떻게 바뀌는지**에 대한 계약은 어디에도 없다. §6.2는 dataset에 대해 "Dtype, frequency와 timezone", "Observation
time과 availability lag"까지 요구하면서, 정작 결과를 크게 좌우하는 commission/세금(예: 증권거래세)/slippage
model에는 같은 수준의 point-in-time 요구(세율이 바뀌는 시점, instrument별 차등 적용)가 없다. §2.3은 "조직별
... cost definition"을 project가 소유한다고만 적을 뿐, qlibx가 cost model을 dataset과 동일하게 등록·버전관리·
lineage에 기록해야 한다는 요구가 빠져 있다.

### 3.2 "Enhanced index"인데 risk method 선언 contract가 없다 *(codex 2차 피드백 반영 — v2의 "risk model 필요" 주장을 완화)*

§10.2는 output으로 "Expected trade, cost와 tracking diagnostics"를 요구하고 "Constraint residual과 binding
constraint"를 말하지만, 실제 optimizer가 ex-ante tracking error를 어떤 방법으로 산출/제약하는지 PRD가 확정하지
않는다. v2는 이를 "risk model(공분산 행렬 또는 factor risk model)이 빠졌다"고 썼는데, 이는 과한 요구다 —
covariance/factor risk model 없이 explicit exposure-band constraint만으로 구성하는 risk-model-free("glass-box")
enhanced index construction도 실무에서 쓰이는 정당한 방법이다(codex는 이 지적의 근거로 S&P DJI 자료를 인용했다.
해당 URL은 접근 권한 문제로 이 리뷰에서 직접 재확인하지는 못했지만, rules-based/constraint-only tilting과
risk-model optimization을 구분하는 것 자체는 index 업계에서 일반적으로 통용되는 구분이므로 주장의 실질은
받아들인다). 필요한 것은 risk model을 강제하는 것이 아니라 **어떤 risk method를 썼는지 선언하는 contract**다.

- `risk_model`: covariance/factor model을 사용한 predicted risk/tracking error
- `scenario`: historical/user-defined scenario 기반 predicted risk
- `constraint_only`: exposure deviation만 통제하고 predicted tracking error는 제공하지 않음
- Ex-post realized tracking error는 이 선언과 무관하게 별도 backtest metric으로 항상 계산한다.

§8.3의 factor exposure는 "있으면" 계산하는 진단이므로 위 선언 없이도 optimizer가 무엇을 근거로 tracking을
통제했는지 사후에 구분할 수 없다는 문제는 그대로 남는다.

### 3.3 qlibx 자체 버전 업그레이드가 기존 catalog를 무효화할 때의 계약이 없다

§9.3은 "Dataset 또는 transitive parent가 바뀌면 dependent identity가 달라진다"까지는 다루지만, **qlibx package
자신의 schema version이 바뀌는 경우**는 다루지 않는다. 오래된 schema version으로 저장된 catalog record를 새
qlibx가 읽을 수 있는지, 못 읽으면 무엇으로 표시되는지(무효/read-only/migration 필요) 요구사항이 없다. (codex의
§4 [P1][WEAK] "Frozen run은 executable environment와 data content를 freeze해야 한다"가 지적하는 content-digest
요구도 같은 방향의 보완책이다 — resolved config·dataset·extension·dependency의 digest가 있으면 최소한 "이
catalog record가 지금 환경과 호환되는지"를 판정할 수 있다.)

이때 "component version이 바뀌면 identity가 달라진다"(§9.3)는 것과 "과거에 저장된 evidence 자체를 더 이상
읽을 수 없다"는 것은 서로 다른 문제이므로 구분해야 한다 — 전자는 새 run이 과거 run과 같은 identity를 주장하지
못하게 막는 lineage 규칙이고, 후자는 이미 완결된 evidence의 가독성 문제다. Package upgrade가 새 run의 identity에
영향을 주는 것과, 과거 evidence가 자동으로 무효가 되는 것은 별개다. 최소 다음 네 상태를 구분해야 한다.

- **Native-readable**: 현재 qlibx가 schema 변경 없이 그대로 읽는다.
- **Read-only legacy**: 읽을 수는 있지만 현재 schema로 다시 발행하거나 새 run의 parent로 쓸 수 없다.
- **Deterministically migratable**: 정의된 migration으로 현재 schema와 동등하게 변환 가능하다.
- **Incompatible/quarantined**: 안전하게 읽거나 변환할 수 없어 evidence로 신뢰할 수 없다고 명시적으로 표시한다.

### 3.4 Nested child strategy가 재귀적으로 spawn 가능한지부터 불명확하고, 가능하다면 자원 한도가 없다 *(codex 2차 피드백 반영 — 재귀가 이미 허용된다는 전제를 수정)*

§7.3은 parent가 child strategy를 spawn할 수 있다고 말하고 nested-research request가 "resource limit"을 명시
한다고 하지만, **child가 다시 child를 spawn할 수 있는지 자체를 PRD가 진술하지 않는다.** "재귀 depth bound가
없다"고 쓰는 것은 재귀가 이미 허용된다고 전제하는 것이라 정확하지 않다 — 순서상 먼저 답해야 할 질문은 "child의
child spawning이 허용되는가"이고, 그 다음에야 "허용된다면 depth/count bound가 필요하다"는 질문이 따라온다.
Product는 nested child recursion을 아예 금지하거나, 허용한다면 maximum depth, 동시에 존재할 수 있는 session 수,
한 run이 소비할 수 있는 총 nested evaluation 개수와 cycle detection을 명시적으로 강제해야 한다.

### 3.5 Signed alpha → physical target까지의 unit/NAV/financing invariant가 없다 *(codex 기여, 채택)*

관련 섹션: §8.1, §8.4, §10.1~10.4, §11.3. `signal`, `signed active weight`, `member coefficient`, `combined
active intent`, `benchmark constituent exposure`, `physical target`이 등장하지만, 어떤 quantity가 어느 NAV에
대한 weight인지, 서로 더할 수 있는 단위인지 명시되어 있지 않다. Fixed dollar-neutral alpha의 long 합은 `1`,
short 합은 `-1`인데 이 숫자를 benchmark weight에 그대로 더하면 200% gross active book이 된다. Flexible budget
alpha의 net이 0이 아닐 때 이 residual이 cash/passive sleeve/financing requirement 중 무엇인지도 하나의 식으로
정의돼 있지 않다. 최소 다음이 필요하다.

```text
dimensionless alpha score
-> declared alpha-to-active-weight policy
-> active weight on declared reference NAV
-> benchmark + scaled active weight
-> feasible physical target + explicit cash
```

이 경계가 없으면 "stored artifact가 public integration point"라는 장점(§1.2)이 오히려 위험해진다. Schema는
맞지만 경제적 단위가 다른 artifact가 조용히 composition될 수 있기 때문이다. §3.1(cost model 부재)과 §3.2(risk
model 부재)는 이 invariant가 있어야 비로소 의미가 확정되는 하위 문제이므로, 이 항목을 함께 고치는 것이 가장
근본적인 수정이다.

### 3.6 Point-in-time contract가 revision/vintage를 표현하지 못한다 *(codex 기여로 일반화, 내 benchmark 사례를 흡수)*

관련 섹션: §6.2, §6.4, §7.3, §15. `observation time + availability lag`만으로는 quarterly fundamental, macro
data, **index/benchmark 구성종목**(내 v1 §2.5의 원래 지적), economic calendar, correction된 market data를
안전하게 표현할 수 없다. 같은 observation/event에 대해 여러 revision이 존재하고, 과거 시점 연구자는 그중 당시
공개된 vintage만 볼 수 있기 때문이다. 최소한 다음 시간을 분리해야 한다.

- `event_time`: 경제적 사건 또는 측정 대상 시점
- `valid_time`: 값이 대표하는 기간
- `knowledge_time`/`published_at`: 이 version을 알 수 있게 된 시점
- `ingested_at`: qlibx project가 해당 version을 수집한 시점
- 필요한 경우 `superseded_at` 또는 revision sequence

구체적 인스턴스: KOSPI200 정기변경처럼 지수 provider가 구성종목 변경을 **발표하는 시점**과 **실제 발효 시점**
사이에 시차가 있는 경우, 위 일반 개념은 benchmark membership에서 각각 다음 구체적 필드로 대응한다(codex
2차 피드백 반영으로 구체화).

- `announced_at` (= `knowledge_time`): provider가 구성종목 변경을 발표한 시점
- `effective_from`/`effective_to` (= `valid_time`의 시작/끝): 그 변경이 실제로 적용되는 기간
- 필요하면 revision/supersede time

`knowledge_time <= decision_time`인 최신 vintage만 노출하는 규칙, 즉 이 경우에는 `announced_at <=
decision_time`인 최신 구성만 노출하는 규칙이 없으면 enhanced index의 benchmark tracking 자체가 look-ahead를
포함하게 된다. 그리고 strategy가 `announced_at` 이후·`effective_from` 이전에 이 정보를 미리 반영("선반영")할
수 있는지, 아니면 `effective_from`부터만 benchmark target에 반영해야 하는지도 별도 policy로 명시해야 한다 —
두 정책은 서로 다른 look-ahead 허용 범위를 만든다. Correction을 과거 snapshot에 소급 반영할지, 새 dataset
snapshot으로만 발행할지도 정해야 한다.

### 3.7 Stored-alpha ensemble의 temporal/calendar compatibility가 정의되지 않았다 *(codex 기여, 채택)*

관련 섹션: §9.3, §10.1. Ticker alignment만으로 ensemble compatibility가 충분하지 않다. Member가 서로 다른
trading calendar, timezone, decision clock, rebalance frequency, holding horizon, universe, price convention,
availability policy를 가질 수 있다. 공통 decision grid와 as-of alignment rule, slow member의 최대 staleness,
holiday/missing rebalance 처리, 서로 다른 reference NAV/budget scale의 normalization이 계약에 없으면 "strategy를
다시 실행하지 않는 reuse"(§10.1 철학)가 가능하더라도 과거 weight를 미래의 다른 clock에 잘못 붙일 위험이 있다.

### 3.8 Local extension·AI agent에 대한 trust/permission/secret boundary가 없다 *(codex 기여, 채택)*

관련 섹션: §2.3, §4.6, §5, §12.1~12.2, §15. Project-local Python extension은 사실상 arbitrary trusted code다.
Dataset, credential, filesystem, network, subprocess에 접근할 수 있고 frozen boundary 밖의 data를 읽거나
artifact를 위조할 수도 있다. "public contract만 사용한다"는 instruction은 security control이 아니다. v1에서는
이 항목을 다루지 않았는데, PRD가 "여러 agent가 하나의 repository에서 자율적으로 local extension을 추가"하는
것을 핵심 철학(§1.2)으로 내세우는 만큼, 최소한 local extension이 trusted code인지, secret이 config/artifact/log에
들어가지 않게 하는 redaction rule이 있는지는 v1 다음 개정에서 반드시 짚어야 할 공백이었다.

### 3.9 Qlib 자체의 버전 호환 정책이 없다

PRD는 "Qlib을 fork하지 않는다"(§11.2), "Qlib의 core order/fill/account/backtest engine을 대체하지 않는다"(§2.4)를
반복하지만, 어느 Qlib 버전 범위를 지원 대상으로 삼는지, upstream Qlib API가 바뀌면(특히 matched-capitalization이
의존하는 Position/Account 내부 동작처럼 공개 계약이 아닐 수 있는 부분) qlibx가 어떻게 대응하는지에 대한 요구사항이
없다.

### 3.10 Catalog 성장에 대한 retention/archival 정책이 없다

§9.2~9.4는 catalog가 모든 successful/failed/invalid run을 하나의 queryable database로 모은다고 요구하는데,
catalog 자체가 무한히 커질 때 query 성능이나 nearest-neighbor 탐색의 실용성을 어떻게 유지할지 요구가 없다.
(§2.1 수렴 지점 표 참조 — codex의 §5 [P2][MISSING]과 동일 결론.)

"Evidence를 지우지 않는다"(§9.2~9.4 철학)는 원칙을 storage 용량이나 개인정보/보안 삭제 요구와 그대로
충돌시키지 말고, 다음처럼 metadata와 payload를 분리해야 한다(codex 2차 피드백 반영).

- **계속 queryable로 유지**: canonical proposal, run 상태, decision, metric summary, lineage — 이것이
  "새 연구는 기존 evidence에서 시작한다"는 철학이 실제로 의존하는 최소 정보다.
- **archive/GC 가능**: large payload, checkpoint, scratch, diagnostic attachment — 용량이 큰 부분이지만
  나중 연구가 반드시 원본 그대로 다시 읽어야 하는 것은 아니다.
- Payload가 삭제되더라도 그 사실 자체(누가, 언제, 왜 삭제했는지)를 나타내는 tombstone과 provenance는 남긴다.
- Pinning(중요 artifact는 GC 대상에서 제외), export/import, catalog rebuild 절차를 별도로 제공한다.

### 3.11 Research catalog에는 evidence가 있지만 evaluation governance가 없다 *(codex 원리뷰에서 누락했다가 2차 피드백으로 재발견해 추가)*

관련 섹션: §4.4, §9.4~9.6, §13 P4. 실패한 trial과 searched parameter range를 보존하는 것(§9.4)은 좋지만, 같은
evaluation segment를 여러 agent가 반복해서 보고 candidate를 선택하면 그 구간은 사실상 training data가 된다.
§2.5의 "이미 관측한 기간을 true forward out-of-sample로 표시하지 않는다"는 금지 조항만으로는 이 selection bias를
막지 못한다 — 그 표시 자체가 틀리지 않아도, 같은 segment를 몇 번이고 다시 봐서 우연히 좋은 결과를 고르는
false-discovery 문제는 남기 때문이다. 다음 개념이 필요하다.

- Segment role: train / validation / test / sealed holdout / live forward
- 누가 언제 어떤 segment의 metric을 보았는지에 대한 exposure ledger
- Proposal이 허용받은 search budget과 실제 trial count
- Multiple-testing 또는 false-discovery 진단
- Holdout unlock 조건, reviewer, unlock 이후 해당 segment 지위 변화
- Promotion evidence(sealed segment 기반)와 exploratory evidence(자유롭게 반복 조회한 segment 기반)의 구분

§9.5의 orthogonality가 높다는 사실은 statistical validity를 대신하지 않는다. "새 연구는 기존 evidence에서
시작한다"는 §1.2 철학을 지키려면, evidence가 존재한다는 사실뿐 아니라 그 evidence가 이미 얼마나 소비됐는지도
catalog가 추적해야 한다.

## 4. Weak — 있지만 목적에 비해 약한 것

### 4.1 Orthogonality 평가에 쓰이는 metric들의 scale-sensitivity가 구분되지 않는다 *(codex 2차 피드백으로 수정 — v2의 "correlation 왜곡" 주장은 수학적으로 틀렸음)*

§9.5는 empirical orthogonality를 correlation/overlap으로 정의하고 "Low PnL correlation만으로 independence를
인정하지 않는다"고 옳게 경계한다. v2는 여기서 "서로 다른 budget 정책의 scale 차이가 correlation 계산을
왜곡할 수 있다"고 썼는데 이는 부정확하다 — Pearson correlation은 `corr(X, Y) = cov(X, Y) / (std(X)·std(Y))`로
정의되므로 한쪽을 양의 상수로 rescale해도(`corr(cX, Y) = corr(X, Y)`, `c > 0`) 값이 바뀌지 않는다. 즉
alpha weight를 2배로 키워도 correlation 자체는 왜곡되지 않는다.

실제 문제는 correlation이 아니라 §9.5가 함께 나열하는 다른 metric들이다 — holding distance, turnover notional,
trade overlap, marginal PnL, concentration, capacity는 correlation과 달리 scale-sensitive하다. 두 alpha의 budget
정책이 다르면 이 metric들은 "같은 mechanism을 다른 크기로 표현한 것"과 "실제로 다른 mechanism"을 구분하지 못하게
왜곡될 수 있다. Orthogonality contract는 metric별 scale semantics(scale-invariant인지 아닌지)와, scale-sensitive
metric에 대해서는 raw 비교와 common-budget-normalized 비교를 모두 제공할 것을 명시해야 한다. 또한 sign
reversal(`corr(-X, Y) = -corr(X, Y)`)은 scale과는 별개의 문제이므로, "parameter/sign/scale variation과 genuinely
separate alpha family를 구분해야 한다"(§9.5)는 요구에서 sign은 scale과 분리해 다뤄야 한다.

### 4.2 Catalog 상태와 decision 상태의 lifecycle이 섞여 있다 *(v1에서 "creative"로 잘못 분류했던 항목 — 승격)*

관련 섹션: §9.2, §9.6, §13 P4. `successful`, `failed`, `invalid`, `incomplete`, `rejected`, `promoted`,
`superseded`가 등장하지만 **run execution status**(그 trial이 끝까지 실행됐는가)와 **research decision
status**(그 결과를 채택했는가)가 한 목록에 섞여 나열된다. Successful run이 rejected alpha일 수 있고, invalid
run이 promotion 대상은 아니지만 diagnostic evidence로는 유효할 수 있다. 다음 세 state machine으로 분리하는 것이
낫다.

- Attempt lifecycle: `proposed → running → completed / failed / cancelled / invalid`
- Artifact verification: `pending → verified / corrupt / incompatible / quarantined`
- Research decision: `exploratory → retained / promoted / rejected / superseded`

각 transition의 actor, compare-and-swap version, append-only audit event를 정의하면 §9.7의 stale
update/crash recovery acceptance도 명확해진다. v1은 이 내용을 "promotion lifecycle을 만들면 좋겠다"는 5장의
창의적 제안으로 적었지만, 위 세 상태가 이미 §9~13에서 실제로 섞여 쓰이고 있다는 점에서 이는 "있으면 좋은 것"이
아니라 **acceptance criteria가 pass/fail을 판정하지 못하게 만드는 현재형 결함**이다. codex의 지적을 원문과
대조한 뒤 이 판단이 맞다고 확인했다(§2.1 참조).

### 4.3 Matched-capitalization reserve의 기회비용이 성과 diagnostics에서 구분되지 않는다 *(codex 2차 피드백 반영 — canonical PnL 차감이 아니라 diagnostic 분리 문제로 재정의)*

§11.6은 borrow fee/margin을 모델링하지 않는다고 정직하게 선언하지만, baseline reserve를 미리 확보해야 한다는
사실이 만드는 **자본 기회비용**은 §11.5 output 목록에 없다. 다만 이 기회비용은 실제 realized PnL이 아니라
counterfactual(어떤 대체 투자나 hurdle rate를 고르느냐에 따라 값이 달라짐)이므로, canonical active PnL에서
자동으로 차감해야 한다는 뜻으로 읽혀서는 안 된다. §11.5는 다음을 서로 분리해서 제공해야 한다.

- 실제 reserve balance와 peak/average utilization
- Reserve 부족으로 실행하지 못한 short intent(§11.6이 이미 리스크로 인지한 "Universe 교체가 잦으면 ... reserve
  사용이 증가한다"와 직결)
- Reserve cash에 실제 발생한 interest/carry
- User-defined alternative를 사용한 opportunity-cost **scenario**(선택적 진단, canonical 수치 아님)
- Active return(booksize 대비)과 total committed-capital return(booksize + reserve 대비)을 각각 별도로

### 4.4 Fixed-budget default의 provenance와 before/after observability가 약하다 *(codex 2차 피드백 반영 — "철학과 모순"이라는 표현을 정정)*

§8.4는 "Default는 research convenience를 위한 fixed dollar-neutral rescale"이라고 **명시적으로 공개**하고
있으므로, 이 default의 존재 자체를 "추측하거나 조용히 fallback한다"(§6.2)는 silent inference 금지 원칙 위반으로
부르는 것은 과했다 — PRD가 스스로 밝힌 default이기 때문이다. 실제 약점은 다른 데 있다: 이 default가 실제로
어떤 run에 적용됐는지, raw signal 강도가 어떻게 지워졌는지를 **관측할 수 있는 acceptance 요구**가 부족하다는
점이다. 다음을 요구하는 방향으로 보강해야 한다.

- Effective config(§6.6)에 어떤 budget policy가 적용됐는지 materialize한다.
- 결과 artifact에 `default-applied` 여부를 표시한다.
- Raw signal, pre-budget weight, post-budget weight를 각각 보존한다(§8.5의 weight snapshot과 연결 가능).
- Orthogonality/incremental 평가(§9.5)에서 raw signal 품질과 budgeted portfolio 품질을 분리해서 평가한다.

### 4.5 StrategyAgent output union이 지나치게 열려 있어 layer contract를 무너뜨린다 *(codex 기여, 채택)*

관련 섹션: §7.2, §12.1. Strategy output이 signal, weight, order 또는 "declared payload" 모두일 수 있다는
유연성은 local extension에는 편리하지만, alpha transform/ensemble/optimizer/execution adapter 중 무엇을
적용해도 되는지 타입만으로 판단하기 어렵다. 최소한 `SignalDecision`(rank/transform 가능, 직접 주문 불가),
`ActiveWeightDecision`(budget/ensemble/portfolio construction 가능), `PhysicalTargetDecision`(optimizer 통과
후), `OrderDecision`(execution policy 소유, Qlib adapter 전용), `DiagnosticPayload`(decision authority 없음)처럼
output kind별 capability를 분리해야, parent가 child output을 composition할 때 output kind와 data/time boundary
호환성을 validate할 수 있다.

### 4.6 Acceptance criteria(P0~P7)가 capability checklist이며 검증 가능한 release contract가 아니다 *(codex 기여, 채택)*

관련 섹션: §13 전체. 대부분 "제공한다", "사용할 수 있다", "관측할 수 있다" 수준이라 pass/fail fixture와 허용
tolerance를 만들기 어렵다. 각 criterion에 canonical test scenario, determinism이 byte equality인지 numerical
tolerance인지, crash/recovery test matrix, dataset/portfolio 크기별 performance envelope, schema
migration/backward compatibility 기간이 필요하다. 또한 `P0`라는 표기가 일반적으로 최고 우선순위로 읽히는데
현재 P0~P7은 실제로는 priority가 아니라 capability group 번호라서, 문서를 읽는 사람이 "무엇을 먼저 만들어야
하는가"를 acceptance criteria만으로는 알 수 없다.

## 5. Wrong / 모순 — 원칙끼리 충돌하는 지점

### 5.1 Determinism 요구와 stochastic/AI 예외가 같은 acceptance 아래 공존한다 *(v1에서 Weak였던 항목을 fact check 후 Wrong으로 승격)*

관련 섹션: §7.1, §7.5, §13 P2, §15. §7.1은 같은 context/version/state/seed에서 같은 result를 요구하면서
"embedded LLM처럼 stochastic한 경우"를 예외로 인정한다. 그런데 §13 P2 acceptance는 예외 조건 없이 "같은 bounded
input, version, state와 seed는 같은 StrategyAgent result를 만든다"고 서술한다. §15는 provider-specific
runtime의 재현성을 qlibx 책임 밖으로 둔다. 세 문장은 동시에 acceptance criterion이 될 수 없다 — §7.1이 인정한
예외가 §13에서는 사라졌기 때문이다. (§2.3 fact check에서 원문 대조로 확인.)

Run을 최소 세 등급으로 나누는 것이 낫다.

1. **Deterministic**: 동일한 frozen input/implementation에서 byte-equivalent 또는 semantics-equivalent result를
   요구한다.
2. **Seeded stochastic**: RNG algorithm, library version, seed stream, parallelism 조건까지 freeze하고 정해진
   tolerance 안의 replay를 요구한다.
3. **Externally stochastic**: provider response, model revision 등으로 replay를 보장하지 않는다. Cache
   reuse/canonical promotion은 별도 policy를 적용하고 raw request/response identity와 non-reproducible flag를
   남긴다.

Resume equivalence(§7.5)도 이 등급별로 정의해야 하며, 외부 AI strategy까지 uninterrupted run과 동일한
observable result를 요구하면 구현 불가능한 보장이 된다.

### 5.2 Same-branch parallelism의 보장 범위가 §2.4 out-of-scope와 충돌한다 *(codex 기여, fact check 후 채택)*

관련 섹션: §1.2, §2.4, §4.7, §9.7, §13 P4. PRD는 worktree 없이 같은 branch에서 여러 agent가 자동으로 안전하게
연구할 수 있다고 하는 동시에, Git branch/worktree/merge 관리는 out of scope로 둔다. §9.7의 10개 항목을 원문으로
재확인하면 전부 qlibx가 관리하는 상태(session isolation, frozen config, catalog identity/publish 충돌 감지)에
대한 보장이고, 두 agent가 같은 local extension 파일이나 project config 파일을 filesystem 수준에서 동시에 직접
편집하는 경합까지는 다루지 않는다. "같은 repository와 branch에서 병렬 연구"를 다음 두 범위로 분리해야 한다.

- **qlibx-owned runtime state**: session isolation, immutable input, atomic publication, duplicate/conflict
  detection을 제품이 보장한다.
- **user-owned source/config edits**: qlibx가 conflict-free를 보장하지 않는다. Run start 이후 edit이 실행 의미를
  바꾸지는 않지만(§9.7 3번), edit 자체의 merge/overwrite는 caller와 repository workflow의 책임이다.

§13 P4의 "최소 세 agent" acceptance test도 qlibx-managed state에 한정해야 한다. 그렇지 않으면 acceptance가
qlibx가 통제하지 않는 editor/Git 동작에 의존하게 된다.

### 5.3 "Portable artifact"와 unrestricted serializer 사이의 긴장 *(codex 기여를 약화된 등급으로 채택)*

관련 섹션: §1.2, §12.3~12.4, §13 P7. §12.3은 recordable Python type이나 serializer 목록을 제한하지 않으면서
동시에 portable format과 독립 loader를 요구한다. codex는 이를 [WRONG]으로 분류했는데, 재검토 결과 이 문서는
같은 정도로 강한 모순이라기보다 **약한 긴장(under-specification)** 이라고 판단한다 — §12.3이 "필요한 결과는
저장된 payload의 의미와 loader가 명확"함이라고 실제 요구사항을 명시하고 있어서, "serializer 목록을 제한하지
않는다"는 문장은 canonical list를 처음부터 고정하지 않겠다는 뜻으로도 읽을 수 있기 때문이다. 다만 실제
구현에서 arbitrary pickle 같은 environment-bound 방식이 "portable"을 자칭할 위험은 실재하므로, artifact payload를
**Portable canonical**(versioned JSON/Parquet/Arrow 등 독립 loader 존재) / **Environment-bound
checkpoint**(resume 전용, exact environment 필요) / **Diagnostic attachment**(canonical integration에 사용 불가)
세 등급으로 나누는 codex의 제안은 채택할 가치가 있다. 같은 맥락에서 §12.4가 최종 HTML/image/document를
"artifact가 아니다"라고 하는 것도, "canonical research evidence가 아니다"까지는 맞지만 lineage가 있는 생성물의
provenance(어떤 input·renderer version으로 만들었는지)까지 버릴 이유는 없다 — `report artifact/deliverable`로
분류해 source artifact reference와 renderer version은 유지하는 편이 낫다.

### 5.4 Endowment 메커니즘이 market execution authority와 account administration authority를 구분하지 않는다 *(codex 2차 피드백 반영 — "두 번째 execution engine" 표현을 정정)*

§2.2는 "qlibx는 Qlib input을 adapt하고 output을 관측할 수 있지만, Qlib account와 별도로 움직일 수 있는 두 번째
execution engine을 유지해서는 안 된다"고 못박고, §2.5는 "Long leg와 short leg를 관계없는 account에서 실행한 뒤
PnL만 합친다"를 금지 행위로 명시한다. 그런데 §11.4는 baseline endowment를 "exchange fill이 아닌 zero-cost
capitalization"(4번 항목)이라고 설명한다. 즉 이 이벤트는 Qlib의 정상 order→exchange→fill 경로를 거치지 않고
account 상태를 직접 바꾼다는 뜻이다.

정확히 짚어야 할 것은(codex 2차 피드백 반영): 이것이 §2.2가 금지하는 "**별도로 움직이는** 두 번째 execution
engine"은 아니라는 점이다. Qlib의 정상 execution은 `Exchange.deal_order()`가 tradability와 dealt amount를 정한
뒤 `Account`/`Position`을 갱신하고, matched-capitalization의 capitalization event는 `Position.update_order()`를
직접 호출해 **같은** Qlib `Position` 객체를 바꾼다 — 별도 account나 독립된 가상 fill engine을 유지하는 게
아니다. 따라서 "두 번째 execution engine을 만든다"는 단정은 부정확하고, 정확한 문제는 **PRD가 "market execution
authority"(Qlib dealt fill)와 "account administration authority"(zero-cost capitalization처럼 Qlib fill 외부의
정당한 account-state 조작)를 별개 개념으로 정의하지 않는다는 것**이다. (이 흐름은 이번 최종 검토에서 설치된
`.venv/Lib/site-packages/qlib/backtest/`의 실제 소스로 다시 확인했다 — `exchange.py:421` `deal_order()`는
`check_order()`로 tradability를 먼저 확인한 뒤 `trade_account.update_order(...)`를 호출하고(또는 `Account` 없이
`position.update_order(...)`를 직접 받는 저수준 overload도 있으나, 실제 backtest executor 루프는 항상
`trade_account`를 넘긴다), `account.py:203` `Account.update_order()`는 매수/매도 순서만 다르게
`self.current_position.update_order(...)`를 호출한다. 즉 executor가 쓰는 정상 경로는
`Exchange.deal_order → Account.update_order → Position.update_order` 순서로 tradability check를 거치며,
matched-capitalization은 이 중 `Position.update_order()`만 직접 호출해 앞의 tradability check와 account
bookkeeping을 모두 건너뛴다는 codex와 architecture review의 설명이 코드로 정확히 확인된다.)

codex도 §3 [P0][WRONG] 1번에서 독립적으로 같은 결론에 도달했다: "matched-capitalization activation은 exchange
fill이 아닌 event로 Qlib composite position과 cash를 직접 늘리고 ... 'Qlib이 유일한 authority'는 문자 그대로
성립하지 않는다." codex는 여기서 한 걸음 더 나아가 "Market execution의 유일한 authority는 Qlib dealt fill이다.
Capitalization은 market execution과 구분되는 명시적 account administration event이며, composite account와
baseline sub-account를 하나의 원자적 transaction으로 바꾼다"는 대안 원칙 문구와, 다음 구체적 불변식을 제안한다
— 이쪽이 v1의 서술보다 실행 가능한 수정안이므로 채택한다.

- Capitalization/top-up/release의 허용 시점과 event ordering
- Qlib checkpoint와 baseline checkpoint의 하나의 joint commit ID
- 두 state 중 하나만 저장된 crash를 복구하거나 무효화하는 규칙
- Dividend, split, delisting, stale price, FX, cash interest가 `B`, `C`, `A`에 미치는 영향
- `active NAV`, `booksize`, `baseline reserve`, `composite NAV`의 정확한 식
- Endowment가 Qlib public lifecycle 안에서 실제로 가능한지 검증하는 feasibility gate

(참고로 `docs/critical-review-on-architecture-claude.md` §2.3의 수정 내용은 코드 수준에서
`Position.update_order()`가 Exchange fill을 우회하는 직접 mutation임을 확인했는데, 이는 정확히 "PRD 문장만으로는
판단할 수 없었던 것"을 코드를 읽고 나서야 알아낸 사례이며, 이번에 codex가 PRD 문장만으로 같은 결론에 도달한
것과 서로 다른 방향에서 같은 결함을 삼중으로 확인한 셈이다.)

### 5.5 Enhanced index 실행 경로와 matched-capitalization 실행 경로의 관계가 불명확하다 *(codex 2차 피드백에서 P0 격상 제안 — 채택)*

§10~§11 전체를 읽으면 signed alpha가 Qlib 계정에 올라가는 경로가 두 가지로 보인다: (a) ensemble → enhanced
index construction → long-only stock/ETF/cash target → Qlib 정상 execution(§10~§11.1), (b) signed alpha를
직접 matched-capitalization으로 Qlib에 태워 "실행하고 audit"(§11.2 도입부)하는 경로. PRD는 이 둘의 관계를
정의하지 않는다: matched-capitalization은 enhanced index 이전 단계에서 개별/ensemble alpha를 검증하기 위한
순수 진단 경로인가, 아니면 enhanced index를 거치지 않고 signed alpha를 그대로 운용하는 대안 경로인가?

codex의 1차 PRD 리뷰에는 이에 정확히 대응하는 항목이 없었지만, 이 리뷰(v2)를 다시 읽은 2차 피드백에서 codex가
"이 execution-route 구분은 좋은 지적이며 P0 finding으로 올릴 만하다"고 스스로 평가했다. 두 실행 경로가 서로
다른 identity를 갖는지, 같은 alpha가 두 경로를 모두 거쳤을 때 성과 차이를 어떻게 reconcile하는지가 §9.3(identity
and reuse)에 없다는 점에서 우선순위를 올릴 근거가 충분하므로, §7 우선순위 목록에 반영했다.

## 6. Creative additions — 서로 겹치지 않는 3가지 관점 (재구성)

v1의 창의적 제안 중 "promotion lifecycle을 상태 기계로 명시하자"는 codex와의 대조 결과 이미 실제 결함(§4.2)으로
승격되어 이 목록에서 제외했다. 대신 codex의 creative 제안(evidence budget, alpha fragility card, research
portfolio scheduler)과 겹치지 않는 세 번째 관점으로 교체했다.

### 6.1 실행 경제성 관점: Capacity/scalability를 1급 diagnostic으로

지금 PRD는 alpha 품질을 signal 강도·orthogonality·turnover·cost 관점(§8, §9.5)에서는 촘촘히 다루지만, "이
alpha가 실제로 얼마의 AUM까지 스케일 가능한가"라는 **capacity curve**는 어디에도 없다. KOSPI200 안에서도
소형주 유동성은 편차가 크므로, participation-rate 가정과 volume 데이터(§6.3)를 결합해 "booksize가 커질수록
예상 slippage/기회비용이 어떻게 증가하는가"를 exposure analysis(§8.3)나 ensemble diagnostics(§10.1)와 같은 급의
**built-in capacity diagnostic artifact**로 만들 것을 제안한다. 이는 §9.5 "incremental: ... capacity" 항목이
이름만 걸어두고 방법론이 없는 부분을 구체화하는 것이기도 하다. (codex의 관점과 겹치지 않음: codex는 evidence
소비량, alpha의 취약성, research queue 우선순위를 다루고 execution capacity/유동성은 다루지 않는다.)

### 6.2 과학적 방법론 관점: Hypothesis-outcome falsifiability contract

§9.6 bounded proposal은 "Hypothesis와 mechanism"을 텍스트 필드로 요구하지만, 그 hypothesis가 실제로 어떤
관측 가능한 결과를 예측하는지, 그리고 run이 끝난 뒤 그 예측이 맞았는지를 **구조적으로 대조**하는 계약이 없다.
지금 구조라면 hypothesis는 사후에 결과에 맞춰 재해석될 수 있는 자유 텍스트로 남는다. Proposal 작성 시점에
"이 mechanism이 참이라면 A 지표는 이 방향, B 지표는 이 범위여야 한다"는 **사전 falsifiable prediction**을
구조화된 필드로 남기고, run 완료 후 catalog가 예측 대비 실제 결과를 자동으로 대조해 "예측 부합/불일치"
diagnostic을 붙이는 built-in을 제안한다. 이는 §9.5의 semantic/empirical/incremental 3단계 평가와는 다른 축이다
— "이 alpha가 다른 alpha와 얼마나 다른가"가 아니라 "이 alpha를 만든 이유가 실제로 검증 가능했는가"를 묻는다.
(codex의 evidence budget[§8.1]은 "얼마나 많이 봤는가"를 다루고, 이 제안은 "본 것이 예측을 확인했는가"를
다루므로 서로 다른 축이다.)

### 6.3 리스크 방법론 관점: Regime/stress replay를 평균 지표와 분리된 1급 산출물로

§9.5는 orthogonality 평가에 "regime stability"를 항목으로만 나열하고, 다른 모든 metric(§8.1, §9.6)도 기본적으로
"구간 평균" 성격이다. PRD에는 알려진 historical stress window(급락장, 유동성 경색일, 지수 정기변경일,
corporate action 밀집 구간)를 alpha·ensemble·enhanced index portfolio에 표준 재생(replay)하여 평균이 아닌
**꼬리 구간에서의 행동**을 보고하는 built-in이 없다. 이는 §10.2의 solver status/infeasibility, §11.6의
matched-capitalization reserve 소진 위험이 실제로 가장 크게 드러나는 지점이기도 하다. 이 제안은 codex의 "alpha
fragility card"(§8.2, 가용성 지연·비용 배수·parameter jitter 같은 **합성 perturbation**)와 인접하지만 방법이
다르다 — 이쪽은 **실제로 있었던 역사적 사건**을 재생하는 empirical replay이고, codex 쪽은 **가상의 파라미터
교란**을 가하는 synthetic sensitivity test다. 두 방법은 서로 대체재가 아니라 상호보완적이므로, 둘 다 채택하되
서로 다른 built-in으로 유지할 것을 권한다.

## 7. 우선순위 정리 — PRD에 먼저 반영해야 할 항목

두 리뷰를 합쳐 실제 구현 착수 전에 고쳐야 할 순서를 정리하면 다음과 같다. (굵게 표시한 항목이 두 리뷰가
독립적으로 수렴한, 신뢰도가 가장 높은 항목이다.)

1. **Market execution authority와 account administration authority를 구분하고, endowment/matched-capitalization을
   그 구분 위에서 재정의한다**(§5.4) — 세 개의 독립 경로(codex 원문 대조, 내 원문 대조, architecture review의
   코드 대조)가 모두 같은 결함을 가리킨다.
2. Signal→physical target의 unit/NAV/financing invariant를 확정한다(§3.5) — 이것이 정의되어야 cost model(§3.1),
   risk method 선언(§3.2), fixed-budget default provenance(§4.4) 문제도 같은 언어로 풀린다.
3. Determinism을 3등급으로 나누고 §7.1/§13 P2의 모순을 없앤다(§5.1).
4. **Catalog의 attempt/verification/decision state machine을 분리한다**(§4.2) — 두 리뷰가 독립적으로 수렴.
5. Enhanced index 실행 경로와 matched-capitalization 실행 경로의 목적·identity·성과 비교 관계를 명시한다(§5.5) —
   codex 2차 피드백에서 P0 격상을 제안한 항목.
6. Point-in-time contract에 knowledge_time/vintage 개념(benchmark의 announced_at/effective_from 포함)을
   추가한다(§3.6).
7. Research catalog에 evaluation governance(segment role, search budget, holdout unlock 정책)를 추가한다(§3.11).
8. Same-branch parallelism의 보장 범위를 qlibx-owned state로 한정한다(§5.2).
9. Local extension의 trust/security boundary(§3.8), ensemble temporal compatibility(§3.7), StrategyAgent
   output typing(§4.5), catalog compatibility state 4분리(§3.3)를 순서대로 정리한다.
10. **Catalog retention/GC 정책을 metadata/payload 분리로 추가한다**(§3.10) — 두 리뷰가 독립적으로 수렴.
