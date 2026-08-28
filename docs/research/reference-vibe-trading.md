# Reference 조사 — Vibe-Trading

- **대상**: `references/vibe-trading/`
- **출처**: https://github.com/HKUDS/Vibe-Trading, `main`, commit `5cd08ee1bd5c28e856b20acae3d077ed9bd919ce`, MIT
- **조사일**: 2026-08-26
- **성격**: 조사 기록. `references/`는 `AGENTS.md`에 따라 **비권위(non-authoritative)** 이며,
  project manifest가 특정 파일을 명시적으로 승격하지 않는 한 이 문서의 어떤 관찰도 qlibx 설계를
  구속하지 않는다. 이 문서는 결정이 아니라 관찰과 그 근거를 남긴다.
- **비교 기준 문서**: `docs/vqapr-architecture.md` (§1, §2, §4, §6, §9, §10),
  `docs/handoff/2026-08-23-agent-layer.md`, `src/vqapr/`

## 읽은 범위

`agent/backtest/engines/base.py`(1,928줄), `agent/backtest/{runner,validation,run_card,metrics}.py`,
`agent/backtest/engines/{korea_equity,vietnam_equity,crypto,futures_base}.py`,
`agent/src/goal/{models,policy}.py`, `agent/src/strategy_discovery/` 전체,
`agent/src/agent/{loop,skills,grounding,tools}.py`, `agent/src/governance/{ledger,manifest}.py`,
`agent/src/scheduled_research/`, `agent/src/memory/`, `agent/src/factors/`,
`agent/SKILL.md`, `agent/src/skills/{strategy-generate,backtest-diagnose}/SKILL.md`,
`agent/tests/factors/test_lookahead.py`.

---

## 1. 제품 개념

**framework가 아니라 agent 제품이다.**

```
pip install vibe-trading-ai
  vibe-trading        interactive CLI / TUI
  vibe-trading serve  FastAPI + React frontend (+ Electron desktop)
  vibe-trading-mcp    MCP server -> Claude Desktop / Cursor
```

납품물의 규모: MCP tool 74개, finance skill 90개, multi-agent swarm preset 30개,
사전 구축 alpha 462개, market-data source 25개, backtest engine 10개.

사용자는 리테일/프로슈머 트레이더이고 대화로 리서치한다. 플래그십 워크플로우는 **Shadow Account** —
증권사 CSV export -> 행동 프로파일링(보유기간, 승률, 처분효과, 추격매매, 과매매, 앵커링) ->
수익 라운드트립에서 if-then 룰 3~5개 추출 -> 그 룰을 A/HK/US/crypto에 백테스트 ->
실현 손익 대비 delta-PnL을 HTML/PDF 리포트로. "네가 네 규칙을 지켰으면 얼마 벌었나"가 제품이다.

### 층 순서가 vqapr과 뒤집혀 있다

vqapr은 framework가 제품이고 agent는 표면이다 — 아키텍처 §10.4가 *"`agent/`는 호출되지 않는다"*로
못 박았다. Vibe-Trading은 agent loop가 제품이고 backtest engine은 그 도구다.

증거: `backtest/engines/base.py` 안에 `print(json.dumps({"error": ...})); sys.exit(1)`이 그대로 있다.
라이브러리 경계가 없다는 뜻이고, 애초에 라이브러리로 소비될 물건이 아니라는 뜻이기도 하다.

---

## 2. vqapr과 겹치는 것

같은 문제를 각자 풀었고, 결론이 상당히 수렴한다.

| 문제 | vqapr | vibe-trading |
|---|---|---|
| skill 점진 공개 | `SKILL.md`는 when-to-use + 3 rung만, 상세는 `--help` | system prompt에 한 줄 요약만, `load_skill`로 본문, 본문도 **섹션 단위 페이징** |
| 기계 판독 출력 | 한 줄 JSON envelope (`ok/stage/family/failures[code,requirement,observed,examples]`) | run_dir CSV + `run_card.json` + 안정된 refusal token (`hard-gate:zero-trades` 등) |
| 조용한 실패 금지 | `TableSpec` 위반은 run 실패 | 불건전 run은 evidence 0행 + 사유 토큰 |
| 재현 지문 | `register` fingerprint, `FrozenRun.identity` = 동결 선언 전체의 sha256 | `run_card.reproducibility.{config_hash, strategy_hash}` |
| 기록이 다음 run의 입력 | §9 "evidence는 층이다", 기록 테이블 = dataset | `evidence_harness`가 run artifact를 읽어 evidence row 생성 |
| alpha 라이브러리 | built-in `academic` | 462개 + `__alpha_meta__`(formula LaTeX / universe / warmup / columns_required) |
| look-ahead 방어 | bounded View — **접근 불가능성**(§2.2) | AST purity gate + 300행 sentinel test |

특히 `strategy_discovery/models.py`의 다음 규칙은 vqapr §4.5(*"생산자가 주장하지 않는다.
실제로 읽은 것에서 나오므로 위조할 수 없다"*)와 동일한 원칙이다.

> decay verdict는 **read time에 evidence 자체에서 계산**된다 — 저장하지 않고, model memory에서
> 유도하지 않는다.

---

## 3. 갈리는 축 — correctness를 어디에 두는가

**vqapr: 구조적.** PIT은 규칙이 아니라 접근 불가능성(§2.2). Account만 상태를 쓴다(§2.3).
Flow가 시간을 찍는다(§9.1). agent는 호출되지 않는다(§10.4).

**vibe-trading: 규약 + 사후 게이트.** `shift(1)` 관례, AST 순수성 검사, sentinel test,
최종 답변에 대한 정규식 grounding gate, evidence 수집 시점의 hard gate.
**LLM이 런타임 루프 안에 있다.**

이 차이가 실제로 드러나는 지점: `SignalEngine.generate(data_map)`는 **전체 히스토리 DataFrame을
통째로 받는다.** 미래를 볼 수 있다. 방어는 두 겹인데 둘 다 부분적이다.

1. `_align()`이 `shift(1)` — 신호는 항상 다음 봉에 반영된다. 신호 *내부*가 미래를 봤는지는 모른다.
2. `tests/factors/test_lookahead.py`의 sentinel test는 **번들된 zoo alpha에만** 돈다
   (합성 패널 300행 x 10종목, `probe_t=260`의 값이 `t>=270` 구간 오염 후에도 불변인지 검사).
   agent가 방금 작성한 `code/signal_engine.py`는 검사 대상이 아니다.

vqapr의 `available_at` / `DataRequirement` / bounded View에 해당하는 개념이 **아예 없다.**
"PIT-safe fundamentals"는 loader별 관례일 뿐 층이 아니다.

---

## 4. Backtest engine

### 4.1 파이프라인

```
loader.fetch(codes, start, end, interval)            25개 source, auto-detect + ordered fallback
  -> fundamentals / RSSHub events enrichment
  -> SignalEngine.generate(data_map) -> {code: Series}    <- agent가 쓰는 유일한 코드
  -> _align():  종목별 자기 캘린더에서 clip[-1,1] -> shift(1) -> 통합 그리드 -> ffill(limit)
                -> optional optimizer(ret, pos, dates) -> L1 정규화 sum|w| <= 1
  -> _execute_bars():  봉 단위 명령형 실행 (시장 규칙 / 가격제한 / 수수료 / 슬리피지)
  -> calc_metrics + benchmark + validation
  -> artifacts/{trades,equity,metrics}.csv + run_card.{json,md}
```

**하이브리드다.** 목표 weight는 벡터화로 미리 다 계산하고, 체결만 봉 단위 명령형.
qlib(전부 벡터)과 nautilus(전부 이벤트)의 중간.

신호가 곧 가중치다. 별도의 portfolio construction 층이 없고, optimizer는 선택적 callable 하나다.
vqapr의 `portfolio/` + `constraints/` + `PortfolioIntent`에 해당하는 자리가 비어 있다.

### 4.2 눈여겨볼 설계 셋

**(1) 결정 시점 평가를 open 가격으로 한다.**

```python
# a. Value the book at prices observable when orders execute.
# Rebalances happen at the bar open, so using close_df[ts] here
# would let the yet-unknown decision-bar close affect order size.
equity = self._calc_open_equity(data_map, close_df, ts)
```

vqapr §6.1이 `plan_orders`를 execution time의 책임으로 **분리**해 푸는 문제를, 이쪽은
**더 이른 가격을 고름**으로써 푼다. 같은 문제 인식, 다른 해법 — 구조가 아니라 규율.

**(2) 바스켓 단위 현금 클리핑.**

목표 바스켓이 수수료/호가단위 반올림 후 현금에 안 맞으면, 순차로 앞 종목부터 채우는 대신
**전체에 공통 스케일 하나**를 곱한다. 포트폴리오 비율이 보존되고 입력 종목 순서 의존이 사라진다.
vqapr의 constraint projection과 같은 자리이며, 잘 만든 부분이다.

**(3) 드롭된 조정을 기록한다.**

`position_adjustment="hold"`에서 같은 방향 리사이즈 요청은 무시되는데, 조용히 버리지 않고
`dropped_target_adjustments`에 남긴다. `rebalance_tolerance` 밴드도 마찬가지이고, 주석에
측정치가 적혀 있다 — *"0.01% 일간 변동이 30봉 중 19봉에서 포지션을 재고정시켰다.
이건 결정 실행이 아니라 노이즈 거래"*. vqapr §6.4의 zero-dealt 세 사유와 같은 발상.

### 4.3 10개 engine이 실제로 시장을 안다

추상 메서드 4개(`can_execute` / `round_size` / `calc_commission` / `apply_slippage`)와
훅(`on_bar` / `before,after_rebalance_bar` / `limit_band` / `historical_base_price`).
구현 밀도가 진지하다.

- **KRX** (`engines/korea_equity.py`): 전일 종가 기준 +-30% 가격제한을 KRX 틱 그리드로 양자화,
  매도 거래세 0.20%(2026년율), 1주 단위, 당일 왕복 허용(T+1 아님).
  **long-only를 코드로 강제**하며 이유가 *"일봉으로는 차입공매도/업틱룰을 강제할 수 없다"*.
  데이터가 규칙을 지탱하지 못하면 기능을 열지 않는다.
- **Vietnam** (`engines/vietnam_equity.py`): 형식상 T+2 결제를 일봉 위 2봉 홀드로 근사하고
  `vn_settlement_bars`로 규칙 변경에 대비. HOSE +-7% 밴드를 10/50/100 VND 틱에
  상단은 내림, 하단은 올림. 100주 단위, 매도측 개인소득세 0.1%.
- **Futures** (`engines/futures_base.py`): `base_price_fields = ("pre_settle", ...)` —
  거래소는 전일 **정산가** 기준으로 밴드를 건다.

vqapr의 `exchange/venues/`에 `krx`가 있으나 아직 이 밀도는 아니다.
**여기는 순수하게 배울 것이 있는 영역이다** — 특히 "규칙을 강제할 수 없으면 기능을 거부한다"는 태도.

### 4.4 engine이 vqapr보다 약한 곳

| 결함 | 내용 |
|---|---|
| **정지/휴장 데이터 조작** | `_align()`이 `ffill(limit=5)`, 크로스마켓이면 10. 정지 종목의 가격을 **만들어낸다.** vqapr §11.6이 정면으로 다루는 "정지 데이터 없는 KRX daily project"가 여기선 조용한 근사다 |
| **Account authority 없음** | `self.capital`, `self.positions`를 10여 개 메서드가 직접 변경. `intended != committed` 구분이 코드에 없다(vqapr §2.3 대비) |
| **round trip 표현이 부정확** | `trades.csv`는 라운드트립당 2행이고 **진입 행 표식이 `pnl == 0.0`**. 정확히 본전 청산이면 진입 행과 구별 불가. 자기네 `strategy_discovery/run_artifacts.py` docstring이 이 한계를 명시한다. vqapr의 typed `FillBatch`(§6.4)가 애초에 만들지 않는 문제 |
| **자기참조 벤치마크** | `benchmark`를 명시하지 않으면 `bench_ret = ret_df.mean(axis=1)` — **자기 유니버스의 동일가중 평균**. 초과수익이 사실상 선택 효과만 재는데 그렇게 읽히지 않는다 |
| **cadence 개념 없음** | 모든 봉이 결정 봉. 리밸런싱 주기는 신호를 상수로 만들어 표현. vqapr `OperationAgenda`에 해당하는 것이 없다 |
| **warm-up 계약 없음** | zoo alpha는 `min_warmup_bars` 메타를 갖지만 engine이 강제하지 않는다 |

### 4.5 반대로 vqapr에 없는 것

- **통계 검증** (`backtest/validation.py`, 497줄): Monte Carlo permutation test(거래 순서 셔플 ->
  Sharpe/MDD p-value), Bootstrap Sharpe CI, Walk-Forward. config에 `validation` 키만 있으면
  자동 실행되어 `run_card`에 들어간다.
- **measure 어휘** (`backtest/metrics.py`, 640줄): Sharpe, 실현 체결 기준 turnover,
  종목별/청산사유별 귀속.
- **진단 표면**: `risk_xray`, `regime`, `correlation`, `factor_costs`, `rebalance_notes`,
  `benchmark.resolve_benchmark`.

대조: `src/vqapr/analysis/`는 현재 `nav_series / returns / drawdown`(performance.py)과
`information_coefficient / rank_information_coefficient / hit_rate / decay`(signal.py)뿐이다.
Sharpe도 turnover도 없다.

---

## 5. Agentic interface

### 5.1 층

```
user --- AgentLoop (ReAct, 5층 컨텍스트 관리) --- MCP tools(74) --- framework
           |                                       |
           +- Goal ledger                          +- Skills(90, 섹션 페이징)
           |  goal -> criteria -> claims           +- routing block guard (fail-safe)
           |        -> evidence -> audit           +- grounding gate (출력 검증)
           +- Session store / trace / run manifest
```

`agent/loop.py` 상단 docstring이 컨텍스트 관리 5층을 선언한다: microcompact(오래된 tool result
가지치기) -> context_collapse(LLM 호출 없는 접기) -> auto_compact(LLM 구조화 요약 + tail 보호) ->
compact tool(모델이 명시 호출) -> iterative update(N번째 압축은 이전 요약을 갱신).

### 5.2 Goal ledger — 연구 세션이 일급 객체다

`src/goal/models.py`:

```
GoalRecord     objective, ui_summary, protocol, risk_tier,
               token/turn/time budget + used, status, recap
GoalCriterion  완료 전 반드시 커버돼야 할 프로토콜 항목, freshness_requirement, protocol_step
GoalClaim      추적 중인 주장 (claim_type, status)
EvidenceRecord text + criterion_id/claim_id + tool_call_id + run_id +
               source_provider/type/uri + symbol_universe + benchmark + timeframe +
               method + assumptions + artifact_path + artifact_hash +
               retrieved_at + data_as_of + freshness_status + verification_status +
               confidence + caveat + contradicts_claim_ids
AuditRow       criterion별 완료 감사 (result, evidence_ids, notes)
```

`GoalStatus`에 `INSUFFICIENT_EVIDENCE`, `NEEDS_REFRESH`, `BUDGET_LIMITED`, `USAGE_LIMITED`,
`COMPLIANCE_BLOCKED`가 **정식 종료 상태로** 들어 있다. 답을 못 냈다는 것이 실패가 아니라 결과다.

`goal/policy.py`는 목표 텍스트가 실거래 주문으로 읽히면 정규식으로 거부한다
(`reject_live_execution_objective`).

### 5.3 Strategy discovery — 증거로 게이트된 카탈로그

"scalable research를 위해 연구 결과를 어떻게 남기는가"에 대한 이쪽의 답이다.

```
run artifacts (equity.csv, trades.csv, metrics.csv, state.json)
   |  evidence_harness: hard gate 통과해야 함
   |    hard-gate:exit-nonzero / metrics-missing / zero-trades / equity-empty / equity-nan
   v
EvidenceRow(strategy_id, regime, trades_in_regime, return, benchmark, sharpe, maxdd,
            date_ranges, position_size, breakeven_fee_bps, stage, provenance, warnings)
   |  regime  in {bear_market, bull_market, structural}
   |          (벤치마크 252봉 롤링 누적수익 <= -0.10 / >= 0.15 로 봉마다 라벨링)
   |  stage   in {hypothesis, backtest, holdout, shadow, live_canary, retired}
   |          STAGES_REQUIRING_PROVENANCE = {backtest, holdout, shadow, live_canary}
   |  quality: MIN_TRADES=10, MIN_COVERAGE_DAYS=730 -> adequate / marginal / insufficient
   |  decay:   read time 계산. >=90일 aging, >=180일 stale(기본 제외)
   v
query_strategies(regime=...) -> agent
```

세 가지가 특히 좋다.

1. **evidence store는 disposable cache다.** 원본은 run artifact이고 `refresh_strategy_evidence`로
   언제든 재구축. 권위가 하나다 — vqapr §9의 "evidence는 영수증" 입장과 같다.
2. **borderline 밴드.** 임계를 아슬하게 통과한 행은 `borderline` 플래그가 붙고, routing block이
   *"verdict가 아니라 raw 수치를 그대로 인용하라"*고 지시한다. 연구량이 늘수록 판정이
   남용되는 것을 막는 장치.
3. **계산할 수 없으면 None을 쓴다.** 다중 포지션 run에서 sizing-corrected breakeven fee는
   닫힌 형태가 없다(문서화된 측정 오차 1.1~6.5배). 그래서 근사값 대신 `None` +
   안정된 `multi-position-breakeven:` warning. 판정 불가한 run도 같게 취급(fail-closed).

### 5.4 Governance — 방법론의 지문

`governance/manifest.py`: system prompt 해시 + skill별 `(name, content_hash)` + tool 이름 목록 해시 +
선별된 패키지 버전 -> `manifest_hash` 하나.
**timestamp와 run_id는 해시에서 의도적으로 제외** — 같은 방법론이면 다른 날 돌려도 같은 해시가
나와야 *"A run과 B run 사이에 방법론이 바뀌었나"*를 물을 수 있기 때문. 모듈 자체는
`datetime.now()`를 절대 호출하지 않고 호출자가 timestamp를 넘긴다.

`governance/ledger.py`: 해시 체인(각 레코드가 `seq` + `prev_record_hash` + 자기 payload에 commit)
+ 매 write fsync + flock. append 전에 **전체 체인을 검증**하고, 깨져 있으면
`LedgerCorruptionError`로 거부한다 — 이미 변조된 이력 위에 그럴듯한 suffix를 쌓지 않는다.

### 5.5 Grounding gate — 출력 검증

`agent/grounding.py`(2,649줄). docstring이 밝히는 대로 세 가지만 구조로 강제한다.

- market-data 소비자는 **현재 tool-call 배치 시작 전에 잠긴 identity**만 쓸 수 있다
- 최종 가격 주장은 **truncate되지 않은 tool 결과와 모순될 수 없다**
- 이 run의 어떤 tool call도 주고받지 않은 종목에 숫자를 붙일 수 없다

나머지("as-of를 밝혀라", "조언이 아니라 분석이다", "거절할 때는 소리 내어 거절하라")는
**의도적으로 프롬프트에 남겼다** — 정규식 게이트가 정답을 기각하기 때문이라고 명시한다.
이 경계 판단 자체가 참고할 만하다.

### 5.6 fail-safe routing

`strategy_discovery/guard.py`: 4개 tool이 **전부** 등록됐을 때만 routing text를 프롬프트에 넣는다.
예외가 나면 텍스트를 뺀다(never raise). 주석: *"부를 수 없는 tool을 광고하는 것 —
기각된 #896의 정확한 실패 모드"*.

> qlibx의 `vqapr-testbed/FRICTION.md` F-001이 정확히 이 버그다 —
> *"`vqapr agent install`이 문서화되어 있으나 존재하지 않는다"*.
> 그리고 `docs/handoff/2026-08-23-agent-layer.md`가 짚었듯 근본 원인은 없는 명령어가 아니라
> `src/vqapr/agent/skill/README.md`가 만들지 않은 명령어를 현재형으로 서술한 것이다.

---

## 6. vqapr 관점의 관찰

### 6.1 없는 것 (관찰된 의존 순서 기준)

**(a) 연구 질문 단위의 원장이 없다.**
vqapr evidence 층은 *한 run이 무엇을 했는가*를 기록한다. *하나의 연구 질문이 여러 run에 걸쳐
무엇을 확립했는가*를 담는 객체가 없다. Goal ledger가 그 구멍이다. vqapr 철학과 충돌하지 않는다 —
evidence는 여전히 영수증이고 goal ledger는 영수증들 위의 색인이며,
`EvidenceRecord.run_id`가 접합점이 된다.

**(b) `run`이 아무것도 남기지 않는다.**
`docs/handoff/2026-08-23-agent-layer.md` 사실 3: *"`publish`는 오늘 독립 실행될 수 없다.
`publish_run_record`는 in-memory result를 받고 `run`은 아무것도 쓰지 않는다."*
narrow persistence 계획은 맞으나, **스키마를 나중에 던질 질의로부터 역산**하는 편이 안전하다.
그 질의는 "이 전략은 어느 regime에서 몇 번, 얼마나 긴 구간에 대해 검증됐나"이고,
그러면 `.vqapr/runs/<identity>/`에 최소한 (run identity, 동결 선언, 날짜 범위, 결정 횟수,
체결 수, NAV 시계열)이 있어야 evidence harness가 순수 reader가 된다.

**(c) NAV 시계열이 기본 기록에 없다.**
아키텍처 §9.2가 명시한 follow-up. mark 시점에 recorder가 없어 결정 시점에 복사할 NAV가 없다는 것.
**이것이 (a)와 (b)의 전제조건이다** — NAV 시계열이 없으면 어떤 evidence row도 계산할 수 없고,
§5.2가 요구하는 변동성 역가중 ensemble도 성립하지 않는다.

**(d) regime 축이 없다.**
`docs/vqapr-architecture.md`에 "regime"이 0회 등장한다. run record는 단일 slice다.
연구가 100개 run으로 늘면 "언제 통하는 전략인가"가 물어지는데, 그 축이 스키마에 없으면
나중에 소급이 어렵다. regime 라벨링 자체는 벤치마크 롤링 수익률 하나면 되고,
vqapr에서는 그냥 등록된 dataset이다.

**(e) evidence stage ladder가 없다.**
`hypothesis -> backtest -> holdout -> shadow -> live_canary -> retired` +
`STAGES_REQUIRING_PROVENANCE`. 아키텍처 §15-5(*"live로 확장하면 층을 가른 축이 약해진다"*)를
**지금 결정하지 않고** 문을 열어두는 값싼 방법이다. 스키마에 stage 컬럼 하나를 두고
오늘은 `backtest`만 쓰면 된다.

**(f) measure 어휘가 패키지에 없다.**
Sharpe도 turnover도 없으면 소비자가 매번 다시 짜고, 그러면 **두 run의 기록이 비교 불가능해진다.**
§2.4가 valuation을 닫은 이유(*"NAV 정의가 run마다 다르면 두 run의 성과를 비교할 수 없다"*)가
measure에도 그대로 적용된다.

**(g) realized PnL 정의가 미결이다.**
§9.2가 스스로 "기록된 결함"이라 부른 것. Vibe-Trading도 같은 문제를 갖고 있으나
(engine별 `_calc_pnl`, 암묵적 평균단가) 그쪽은 정하고 갔다. 열어둔 채로는 (a)의 evidence 비교가
성립하지 않는다.

**(h) 방법론 지문이 없다.**
agent 층이 전략을 저작하면 **skill 본문이 결과의 입력**이 된다. vqapr은 컴포넌트를 fingerprint하지만
그것을 만든 agent composition은 지문이 없다. `skill install` manifest가 이미 per-file sha256과
source sha를 기록하므로, 그것을 run record에 넣는 것은 작은 작업이다.

### 6.2 가져오지 않을 것

- **grounding gate 통째로.** 2,649줄 정규식은 취약하고, vqapr의 숫자는 LLM이 tool 출력을 읽어
  나오는 것이 아니라 결정론적 코어에서 나온다. 좁은 부분만 값이 있다 — agent 리포트의 모든 숫자는
  그것이 나온 run identity를 달고 다녀야 한다. 메커니즘은 이미 있다(recorder row의 `run_id`).
- **engine 내부의 `print` + `sys.exit`.** 라이브러리 경계 없음.
- **`ffill(limit=N)` 기본값.** vqapr은 §11.6에서 반대로 결정했고 그 결정이 옳다.

---

## 7. 정리

Vibe-Trading은 vqapr이 **의도적으로 짓지 않은 층**을 전부 지어놓은 레퍼런스다.
백테스트 코어의 정합성은 vqapr이 명백히 앞선다(PIT을 구조로 강제, Account 단일 권위,
시간 소유 분리, 정지 데이터를 근사하지 않음). 반대로 **연구가 축적되는 층** —
goal/claim/evidence 원장, regime x strategy 증거 축, 증거 품질 사다리와 decay, 방법론 지문,
통계 검증, measure 어휘 — 은 vqapr에 비어 있고 저쪽에 작동하는 형태로 있다.

그 설계들의 밑에 깔린 원칙(생산자가 주장하지 않는다 / 계산할 수 없으면 None /
read time 유도 / fail-safe 광고)이 vqapr이 이미 쓰는 원칙과 같으므로,
개념을 옮기는 데 철학적 마찰이 없다.

관찰된 의존 순서: **(c) NAV 시계열 -> (b) run 영속화 -> (d)+(e) regime/stage 축 -> (a) goal ledger.**
앞의 셋이 없으면 goal ledger는 참조할 대상이 없다.
