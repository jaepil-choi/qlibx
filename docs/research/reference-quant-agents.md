# Reference 조사 — quant-agents (QRAFTI)

- **대상**: `references/quant-agents/`
- **출처**: https://github.com/terence-lim/quant-agents, `main`, commit `0760c453287c025960bf278d2970557c88cb9de9`, MIT
- **논문**: Lim, T., Muthuraman, K., & Sury, M. (2026). *QRAFTI: An agentic framework for
  empirical research in quantitative finance* [Preprint]. arXiv:2604.18500
- **조사일**: 2026-08-26
- **성격**: 조사 기록. `references/`는 `AGENTS.md`에 따라 **비권위(non-authoritative)** 이며,
  project manifest가 특정 파일을 명시적으로 승격하지 않는 한 이 문서의 어떤 관찰도 qlibx 설계를
  구속하지 않는다. 이 문서는 결정이 아니라 관찰과 그 근거를 남긴다.
- **비교 기준 문서**: `docs/vqapr-architecture.md` (§1, §2, §5, §9, §11.1, §11.2),
  `src/vqapr/`, `src/vqapr/agent/skill/SKILL.md`

## 읽은 범위

전체 5,100줄 Python 17개 모듈 + `README.md` + `DOC.md` + `tests/`.
핵심: `qrafti.py`(Panel, 803줄), `research_server.py`(MCP tool 16개, 677줄),
`research_utils.py`, `portfolio.py`, `report_utils.py`, `report_server.py`, `coding_server.py`,
`shared_agents.py`, `agent_delegation.py`, `evaluate_agent.py`, `client_utils.py`,
`utils.py`(DataCache/Calendar), `data_utils.py`, `rag.py`, `server_utils.py`.

---

## 1. 제품 개념

**논문에 붙은 재현 가능 아티팩트다.** 제품이 아니라 *"LLM 에이전트가 실증 팩터 연구를 수행할 수
있는가"* 라는 주장의 증거물. UT Austin 학술 프로젝트이며, 이 성격이 설계 대부분을 설명한다.

구성은 넷:

```
Financial Intelligence Toolkit   qrafti.Panel — (date, asset) 패널 하나의 자료구조
MCP tool servers                 research(16) + report(2) + coding(1) = 19개
Pydantic-AI agents               research / report / coding / compactor
Streamlit UI                     대화 + 툴 트레이스 + Computation Graph
데이터                            CRSP + Compustat + Fama-French + JKP
```

증명 대상은 세 워크플로우이고 `README.md`가 프롬프트를 그대로 싣는다.

1. **Fama-French HML 재현** — BE 구성 -> 12월 B/M -> 6월 래깅 -> NYSE 브레이크포인트 독립 이중정렬
   -> 시총가중 -> HML
2. **JKP 스타일 12-1 모멘텀 재현** — non-micro 브레이크포인트, NYSE 80분위 winsorized cap 가중
3. **자율 팩터 발명** — *"워런 버핏의 투자 철학을 Compustat 항목으로 구현하는 신규 특성을
   제안하고 검증하라"*

vqapr walkthrough **§11.1 (independent double sort)** 와 **§11.2 (실제 팩터 재현)** 가 정확히 같은
과제다. 현재까지 조사한 레퍼런스 중 **도메인이 vqapr과 가장 정확히 겹치는 것**이다.

규모는 작다. 5,100줄, 플랫 디렉터리, 클래스 4개. 읽을 가치는 규모가 아니라 하나의 결정에 있다.

---

## 2. 그 하나의 결정 — Panel과 panel_id

QRAFTI 전체가 이 문장 위에 서 있다.

> **모든 툴은 `panel_id` 문자열을 받아 `panel_id` 문자열을 반환한다.
> 데이터는 LLM 컨텍스트를 절대 통과하지 않는다.**

```python
def as_payload(self) -> dict:
    self.save()
    return {"results_panel_id": self.name, "nlevels": self.nlevels, "rows": len(self)}
```

에이전트가 보는 것은 이것이 전부다 — 식별자, 인덱스 레벨 수, 행 수. 값은 보지 못한다. 그래서:

- 100만 행 패널을 다뤄도 토큰이 들지 않는다
- **LLM이 숫자를 지어낼 자리가 구조적으로 없다.** Vibe-Trading이 2,649줄 정규식 grounding gate로
  사후에 막는 것을, 여기서는 자료형 하나로 애초에 성립 불가능하게 만든다
- 에이전트의 작업이 "계산"이 아니라 **"어느 패널에 어느 연산을 어느 순서로 걸 것인가"** 가 된다

`Panel`은 (date, asset) 2레벨 MultiIndex의 **단일 컬럼** 래퍼다. 연산 축은 딱 둘이다.

```
panel.apply(func, reference=None)   횡단면 — groupby(date), helper가 한 날짜의 전 종목 DataFrame을 받는다
panel.trend(func, reference=None)   시계열 — groupby(asset), helper가 한 종목의 전 기간을 받는다
```

여기에 산술/비교/논리 연산자, `@`(날짜별 내적), `shift`(날짜 라벨 재지정), `restrict`(필터).
**팩터 연구의 문법이 두 개의 groupby로 닫힌다.** 이 절제가 이 레퍼런스의 실질적 기여다.

> vqapr의 `transforms/`(§5.6 "값을 값으로")와 `portfolio/`(§5.3 "순수 계산 leaf")가 같은 자리인데,
> vqapr에는 **횡단면/시계열 축 구분이 어휘로 드러나 있지 않다.** QRAFTI는 그것을 메서드 이름
> 두 개로 만들었고, LLM이 툴을 고르는 데 이 구분이 결정적으로 작용한다.

---

## 3. vqapr과 겹치는 것

| 문제 | vqapr | QRAFTI |
|---|---|---|
| 계산 결과가 다음 계산의 입력 | 기록 테이블 = 등록된 dataset (§9.1) | 모든 패널이 workspace parquet, `panel_id`로 재참조 |
| 데이터 카탈로그 발견 | `vqapr list datasets` | `Panel_lookup(query, panel_type)` — **RAG 검색** |
| 값 계산과 서술의 분리 | DataModel(척추 밖) / StrategyModel(척추 통과) | 툴이 숫자를 만들고 LLM은 서술만 한다 |
| 기계 판독 출력 | 한 줄 JSON envelope | 모든 툴이 `json.dumps(payload)` 또는 `{"error": traceback}` |
| 재현 대상 | §11.2 "실제 팩터 재현 — 전체 규모 검증" | `tests/` HML/JKP 재현 + ground-truth 패널 |
| 에이전트가 프레임워크를 부른다 | CLI 한 방향 (§10.4) | MCP 한 방향, 서버는 클라이언트를 모른다 |

`Panel_lookup`이 흥미롭다. 데이터셋 카탈로그를 **FAISS + Chroma 임베딩 검색**(`rag.py`,
sentence-transformers `all-MiniLM-L6-v2`)으로 연다. research agent의 system prompt가
*"패널을 조작하는 어떤 툴을 부르기 전에, 필요한 데이터가 이미 사전계산 패널로 있는지
lookup으로 확인하라"* 고 강제한다.
vqapr의 `vqapr list datasets`는 정확 일치 목록이고, 등록 dataset이 수백 개가 되면 같은 문제가 온다.

---

## 4. 갈리는 축 — 무엇을 "결과"라고 부르는가

**vqapr §2.2:** *"위 경로를 통과하지 않고 return/NAV/PnL/turnover를 만드는 코드는 없다."*

**QRAFTI:** 팩터 수익률은 가중치와 수익률의 내적이다. 끝.

```python
def portfolio_returns(port_weights: Panel) -> Panel:
    stock_returns = Panel().load(EXCESS_RETURNS).shift(-1)   # lead-1m 초과수익률
    port_weights = portfolio_impute(port_weights, normalize=True)
    return (port_weights @ stock_returns).shift(1)
```

**이것이 execution 층 전부다.** `research_utils.portfolio_returns` 15줄이 vqapr의
`orders/` + `exchange/` + `account/` + `valuation/` 자리를 통째로 차지한다.

### 4.1 백테스트 엔진이 없다

| vqapr에 있는 것 | QRAFTI |
|---|---|
| Order / Fill / requested vs dealt | **없음** — 체결 개념이 없다 |
| Account (cash, position, version, journal) | **없음** — 계좌가 없다 |
| 거래비용 / 슬리피지 / 호가단위 / 거래정지 | **없음.** 리포트 Table 2에 `T-cost @5bps / @10bps` 사후 추정치만 |
| Exchange / venue 규칙 | **없음** — 시장 개념이 없다 |
| NAV / valuation / mark | **없음** — 수익률만 있고 자산가치가 없다 |
| Constraint | **없음** |
| 빈도 | **월간 고정.** `utils.Calendar`가 `pd.offsets.MonthEnd`, `annualization=12` |

**이것은 결함이 아니라 다른 질문이다.** 학술 팩터 연구에서 "HML의 수익률"은 체결 가능성과 무관한
정의상의 값이고, 자산가격 문헌 전체가 그 규약 위에 서 있다.

의미하는 바: QRAFTI는 vqapr §1.2 일곱 층 중 **Value 층과 Decision 층의 절반**만 구현하고,
**Runtime / Execution / State 셋을 아예 짓지 않기로** 한 것이다.

### 4.2 대신 시점 정렬을 한 함수에 압축했다

```
port_return[t+1] = w[t] · r[t -> t+1]
```

`load(EXCESS_RETURNS).shift(-1)`로 선행 수익률을 만들고, 내적한 뒤 `.shift(1)`로 보유기간
**종료일**에 라벨을 붙인다. 가중치는 언제나 그것이 버는 수익률보다 앞선 날짜이므로
**구성상 옳다.** 다만 이것은 **함수 하나 안의 규약**이지 층이 아니다. 그 위쪽,
즉 특성(characteristic) 자체가 미래를 봤는지는 아무것도 검사하지 않는다.

### 4.3 look-ahead 방어가 프롬프트에 있다

`README.md`의 세 번째 예제 프롬프트를 그대로 인용하면:

> Guidelines:
> - Any data items which are sourced from Compustat Annual **must be lagged six months**
> - When combining components, the components should be first **resampled every June**

**6개월 래그가 사용자 프롬프트에 있다.** 데이터 층이 아니라.

확인 결과 `data_utils.load_pstat`는 `rdq`(Compustat 실적발표일)를 **컬럼으로 로드하지만
아무 데서도 쓰지 않는다.** 패널 인덱스는 `datadate`, 즉 회계기간 종료일이다.
`available_at`에 해당하는 개념이 코드베이스 전체에 존재하지 않는다.

> `src/vqapr/agent/skill/SKILL.md`가 첫 `register` 전에 물으라고 한 바로 그 지점이다:
> *"회계 사실은 그것이 다루는 기간보다 몇 주 또는 몇 달 뒤인 발표 시점에 available하다.
> 기간 종료에 고정 래그를 적용하는 것은 근사이고, 그것이 안전한 근사인지는 vqapr에 대한 판단이
> 아니라 데이터에 대한 판단이다."*
>
> QRAFTI는 정확한 답(`rdq`)을 데이터로 갖고 있으면서 고정 래그 근사를 쓰고,
> **그 근사를 LLM에게 자연어로 지시한다.** 프롬프트가 바뀌면 결과가 조용히 바뀐다.
> vqapr §2.2(*"규칙은 잊히고 캡슐화는 잊히지 않는다"*)의 실물 사례이며,
> 규칙을 잊는 주체가 사람이 아니라 LLM일 때 문제가 더 나빠진다는 것까지 보여준다.

### 4.4 조용한 근사가 두 군데 더 있다

- `research_utils.characteristics_resample(ffill=True)` — 직전 샘플링 시점 이후의 최신 관측을
  목표일로 **캐리 포워드**. 창 안에서만 채우므로 무한 ffill보다는 낫지만 없는 값을 만든다.
- `research_utils.portfolio_impute(drifted=...)` — 월말에 가중치가 없으면 전월 가중치를
  가격 변화로 드리프트시켜 채운다. 툴 docstring이 *"implicitly be imputed"*라고 정직하게
  적어두었으나, 에이전트가 그 문장을 읽었는지는 알 수 없다.

vqapr은 §11.6에서 정지 종목 데이터를 만들어내지 않기로 정했고 `ffill` 기본값을 두지 않는다.
**조사한 레퍼런스 중 이 지점에서 vqapr이 유일하게 엄격하다.**

---

## 5. Agentic interface

### 5.1 층

```
user --- Streamlit / CLI --- Research Agent ---+--- research_server (MCP, 16 tools)
                              (Pydantic-AI)    |
                                               +--- report_agent_tool -> Report Agent -> report_server (2)
                                               +--- coding_agent_tool -> Coding Agent -> coding_server (1)
                                        Compactor Agent (툴 없음, 대화 압축 전용)
```

**서브에이전트를 툴로 노출한다.** `report_agent_tool(panel_id, description)`은 리서치 에이전트
입장에서 그냥 툴이고, 내부에서 다른 에이전트를 돌린다. 위임 계약이 `COMMAND:` 접두 문자열이라
파싱은 프롬프트가 한다 — 취약하지만 의도는 명확하다.

### 5.2 참고할 만한 것 셋

**(1) 툴 docstring이 "언제 쓰지 말 것인가"를 적는다.**

`Panel_lag`(날짜 재라벨링)와 `Panel_characteristics_resample`(다운샘플 + ffill)은 LLM이 혼동하기
쉬운 쌍이다. 그래서 `Panel_lag` docstring에 **`When NOT to use`** 섹션을 두고
*"선택된 월/월말로 다운샘플링할 때 쓰지 말 것"*이라고 명시하며, 반대편 툴도 대칭으로 적는다.

> vqapr에도 같은 혼동 쌍이 있다 — `materialize` vs `run`, `register` vs `new`.
> `--help`가 사용법의 권위라면, **혼동 가능한 이웃 verb를 이름으로 지목해 배제하는 문장**이
> 그 help에 있어야 한다.

**(2) 리포트 툴이 표를 미리 계산해 프롬프트로 돌려준다.**

`report_server.Panel_standardized_report(panel_id, description)`은 리포트를 쓰지 않는다.
**이미 계산된 표가 박힌 프롬프트 문자열**을 반환하고, 에이전트는 그 주위에 산문을 쓴다.

```
Table 1   유니버스 커버리지 (종목 수 / 시총 비중, 기간별)
Table 2   회전율 + T-cost @5bps / @10bps (월간/연간)
Table 3   터셔일 스프레드 포트폴리오 성과 (연율 평균/변동성/왜도/초과첨도/Sharpe/MDD)
Table 4   Panel A 원수익률+t / Panel B CAPM 알파+t+베타 / Panel C FF3 알파+t+로딩
Table 5   size 5분위 조건부 이중정렬, 각 분위별 알파와 t
Figure 1  시장베타=1로 조정한 누적수익 vs Mkt-RF
```

Novy-Marx & Velikov, *Assaying Anomalies*(2024) / *AI-Powered (Finance) Scholarship*(2025)
프로토콜의 구현이며, 소스 주석이 그렇게 밝힌다.

**이것이 "measure 어휘가 없다" 문제의 대안 해법이다.** 메트릭 목록을 표준화하는 대신
**리포트 자체를 표준화**한다. 모든 팩터가 같은 5개 표를 받으므로 비교 가능성이 부수적으로 나온다.
그리고 LLM은 없는 숫자를 쓸 수 없다 — 숫자가 이미 프롬프트 안에 다 있기 때문이다.

**(3) Computation Graph — 리니지를 툴 로그에서 복원한다.**

`server_utils.log_tool(tool, input, output)`이 모든 호출을 파일에 남기고,
`client_utils`가 그것을 읽어 graphviz 그래프를 만든다. 규칙은 하나다.

> 툴 입력 인자 중 **키 이름에 `panel_id`라는 문자열이 들어간 것**은 전부 입력 간선이고,
> 출력의 `results_panel_id`가 노드다.

BFS로 루트(어떤 입력에도 나타나지 않는 노드)를 찾아 그린다.
**선언 없이 리니지가 나온다** — 모든 툴이 (panel_id -> panel_id) 모양이라는 규율 하나 덕분이다.

구현은 취약하다. 로그가 `indent=2` + 빈 줄 구분이라 JSONL이 아니고, 그래서 손으로 짠 중괄호
상태 머신으로 파싱한다. 간선 판정이 문자열 substring 매칭이다.
**다만 아이디어는 vqapr에 이식 가능하며, vqapr 쪽 구현이 오히려 더 튼튼할 수 있다** —
봉투 다섯 컬럼(`run_id / producer_id / stage / event_time / sequence`)이 이미 타입으로 찍히기 때문.

### 5.3 참고하지 않을 것

- `coding_server.execute_python`에 **샌드박싱이 없다.** `run_code_in_subprocess`로 서브프로세스에
  던지고 stdout을 받는 것이 전부. 자율 에이전트가 임의 코드를 실행한다.
- 에러가 `{"error": traceback.format_exc()}` — 파이썬 트레이스백 원문.
  vqapr의 `{code, requirement, observed, examples}`가 비교 대상이 아닐 만큼 낫다.
- 위임 계약이 `COMMAND:` 문자열 프롬프트 파싱.
- research agent system prompt의 *"툴 호출이 예상치 못한 에러를 냈으면 같은 파라미터로 한 번 더
  불러라"* — 결정론적 툴에 대한 맹목 재시도.
- `utils.DataCache`가 단조 증가 카운터(`_1`, `_2`, ...). 해시도 메타데이터도 내용 주소화도 없고,
  `cache.json`은 `file_id` 하나만 담는다. `reset()`이 전부 지운다.
  **패널 자체에는 출처가 없고** 출처는 오직 로그 파일에만 있다 — 로그가 잘리면 리니지가 사라진다.

---

## 6. corr@k — 에이전트 연구를 정량 평가한다

`evaluate_agent.py`(110줄). 현재까지 조사한 레퍼런스 중 **여기에만 있는 것**이며,
이 레포에서 가장 참고할 가치가 큰 부분이다.

```
tests/test_book_value.query   프롬프트. 끝에 "최종 패널의 results_panel_id만 반환하라.
                              에러로 완료할 수 없으면 정확히 `MODEL ERROR`를 반환하라."
tests/test_ff.py              참조 구현. 같은 계산을 직접 짜서 ground-truth 패널을 만든다
agent_cli.py test_book_value  같은 쿼리를 N회 실행 -> .responses (panel_id 목록)
evaluate_agent.py             각 응답 패널을 ground와 상관 -> corr@k
```

```python
def corr_k(correlations, k):
    """크기 k의 모든 부분표본에 대해 그 안의 최대 상관을 취하고, 모든 부분표본에 걸쳐 평균."""
    return mean(max(correlations[j] for j in subset)
                for subset in itertools.combinations(range(N), k))
```

**pass@k를 연속값 연구 산출물로 옮긴 것이다.** 정답/오답이 아니라 "정답 패널과 얼마나 상관되는가"
이고, k를 키우면 "k번 시도하면 재현에 도달하는가"가 나온다.
`k = 1, 2, 3, 5, N`을 한 줄로 CSV에 append하며 그것이 논문 표가 된다.

테스트가 층으로 쌓인 것도 참고할 만하다.
`test_book_value`(BE 구성만) -> `test_book_market`(B/M까지) -> `test_hml_returns`(HML 전체)
-> `test_hml_reflexion`(같은 과제를 Reflexion 프롬프트로).
그리고 각각에 `test_code_*` 짝이 있는데, *"coding_agent_tool과 Panel_lookup만 써라"*로 제한한
변형이다 — **툴 경로가 결과를 얼마나 바꾸는지를 통제 변수로 측정한다.**

> qlibx의 **Spawn Gate**(`docs/handoff/2026-08-23-agent-layer.md`) —
> *"fresh agent가 `vqapr-testbed/`에서 측정한다: vqapr 귀속 `blocked` friction 0건,
> `slowed` 최대 2건, rung마다 첫 호출이 3회 이내 성공"* — 은 같은 발상의 정성적 버전이다.
> corr@k는 그것을 **수치로, 반복 가능하게, 회귀 검출 가능하게** 만든 형태다.
> vqapr은 이미 §11.2(실제 팩터 재현)와 §11.7(실제 인핸스드 인덱스 연구)이라는
> ground truth 후보를 문서에 갖고 있다.

---

## 7. vqapr 관점의 관찰

`docs/research/reference-vibe-trading.md`에 적은 항목과 겹치지 않는 것만 남긴다.

**(A) 표준 리포트를 고정하는 것이 메트릭 목록을 고정하는 것보다 낫다.**
메트릭 목록은 늘어나기만 하고 누가 무엇을 봤는지가 남지 않는다. 리포트를 고정하면
커버리지 / 회전율 / 비용민감도 / 팩터모형 통제 / 사이즈 조건부까지 **빠뜨릴 수 없게** 된다.
§2.4가 valuation을 닫은 논리(*"NAV 정의가 run마다 다르면 두 run의 성과를 비교할 수 없다"*)가
그대로 적용된다. Novy-Marx-Velikov 프로토콜이 학계 표준에 가깝고 vqapr walkthrough의 팩터 재현
과제와 결이 같다.

**(B) 숫자는 툴이 계산하고 에이전트는 서술만 한다.**
`Panel_standardized_report`가 **표가 박힌 프롬프트**를 돌려주는 패턴. vqapr은 이미 결정론적 코어를
갖고 있으므로 이 패턴을 쓰면 Vibe-Trading식 grounding gate가 필요 없어진다.
agent 표면에 "리포트 프롬프트 생성" verb 하나면 성립한다.

**(C) 리니지 그래프 — 재료가 이미 다 있다.**
recorder 봉투 다섯 컬럼과 `FrozenRun.identity`, `DataRequirement`가 이미 노드와 간선을 정의한다.
QRAFTI가 substring 매칭으로 얻는 것을 vqapr은 **타입으로** 얻을 수 있다.
없는 것은 그것을 읽어 그리는 소비자뿐이며, 이는 run 영속화 작업의 부산물이다 —
`.vqapr/runs/`에 "이 run이 소비한 dataset id 목록"을 넣으면 그래프가 따라온다.

**(D) corr@k 재현 벤치마크.**
Spawn Gate를 정량화한다. `showcases/`나 `experiments/`에 ground-truth 산출물을 동결하고,
같은 자연어 과제를 N회 돌려 상관을 잰다. **프레임워크 변경이 에이전트 성공률을 떨어뜨렸는지를
회귀로 검출**할 수 있는 유일한 수단이다. 현재는 사람이 friction log를 읽는 것 외에 방법이 없다.

**(E) 툴 문서에 "언제 쓰지 말 것인가"를 적는다.**
혼동 가능한 이웃 verb를 이름으로 지목해 배제. `--help`에 한 문단.

**(F) 카탈로그를 자연어로 연다.**
`vqapr list datasets`가 정확 일치라면 등록 dataset이 수백이 되는 순간 에이전트가 찾지 못한다.
RAG까지 갈 필요는 없고, 등록 시 description을 필수로 받고 부분 문자열 검색을 여는 것으로 대부분
해결된다. **다만 description을 필수로 할지는 지금 정해야 소급이 가능하다.**

**(G) 횡단면/시계열 축을 어휘로 드러낸다.**
`apply`(date별) / `trend`(asset별). vqapr `transforms/`에는 이 구분이 이름에 없다.
팩터 연구에서 두 축은 **다른 종류의 look-ahead 위험**을 갖는다 — 시계열 축은 미래를 볼 수 있고
횡단면 축은 원리적으로 볼 수 없다. 이름이 갈려 있으면 검사할 자리도 갈린다.

---

## 8. 세 레퍼런스의 위치

```
                  Value/Decision만          Decision+Execution        전 층 + 구조적 PIT
                  -----------------------------------------------------------------------
 도메인 근접도     QRAFTI                    Vibe-Trading              vqapr
 PIT 강제          프롬프트 (자연어)          규약 (shift(1)+테스트)     구조 (접근 불가능성)
 결과의 정의       w · r                     체결된 계좌                체결된 계좌 + 4단계 구분
 에이전트 위치     MCP 클라이언트             런타임 루프 안             CLI 밖 (호출되지 않음)
 연구 축적         panel graph + corr@k      goal ledger + evidence    (없음)
 표준 측정         고정 리포트 5표            metrics + validation      (없음)
```

QRAFTI가 vqapr에 주는 고유한 것은 둘이다 — **표준화된 리포트를 측정 권위로 삼는다**는 것과
**에이전트 연구를 corr@k로 정량 평가한다**는 것. 나머지(Panel 추상화, 툴 서버 경계, 리니지 그래프)는
vqapr이 이미 더 나은 재료로 갖고 있고 소비자만 없다.

반대 방향의 확인도 하나 얻었다. QRAFTI는 `rdq`를 데이터로 갖고도 6개월 고정 래그를
**프롬프트로** 지시한다. 자연어 지시로 PIT을 강제하려는 시도가 실제로 어떤 모습인지 보여주는
사례이며, vqapr의 bounded View 설계를 뒷받침한다.
