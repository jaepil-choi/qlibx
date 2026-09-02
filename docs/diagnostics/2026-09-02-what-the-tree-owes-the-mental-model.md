# 2026-09-02 평가 — 트리가 mental model에 아직 빚진 것

| | |
|---|---|
| **작성 시각** | 2026-09-02 KST (+09:00) |
| **기준 커밋** | `develop @ 1ec2b8d7`. 이 문서의 모든 수치는 그 커밋에서 **직접 측정**했다 |
| **트리 상태** | `pytest tests/ -q -rs` → **1292 passed, 14 deselected** · `ruff check src/` → clean · 133 modules / 30,260 lines |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` (§17 소유자 mental model) → `docs/design/the-panel-the-surface-and-the-run.md` |
| **수정 여부** | **production 코드 수정 없음.** 이 문서와 함께 들어간 것은 문서 정리뿐 — `docs/issues/README.md` 신설, `035`·`036`·`046`·`047` status 갱신, `docs/diagnostics/archive/`로 두 건 archive |
| **선행 문서** | `2026-08-31-vqapr-structural-refactoring.md` · `2026-08-31-post-step-07-review.md` · `2026-09-01-the-read-path-campaign.md` |

---

## 0. 총평 — 진단은 이미 다 나와 있다. 없는 것은 착수다

**세 개의 진단 문서가 이미 옳고, 소유자 ruling도 이미 나 있다.** 이 평가가 새로 발견한 구조적
결함은 없다. 발견한 것은 **결정과 트리 사이의 간격**이다.

| 결정 | 언제 | 트리 상태 (2026-09-02 측정) |
|---|---|---|
| `036` CONVERGE — 두 Model 역할은 같은 방식으로 저작된다 | 2026-08-31 | **절반.** 읽기(5–9행)는 record `128`, lookback은 `126`. **class 계보 둘은 그대로** |
| `040` — agenda는 공유 가능하다 | 2026-08-31 | **미구현** |
| `035` — 검증은 읽기 경로에서 일어나지 않는다 | 2026-08-31 | **절반.** 앞 절반은 record `119`. columnar accessor는 "레인 C 후 재측정" — 레인 C는 병합됐고 **차단이 풀렸는데 아무도 재지 않았다** |
| Panel · Surface · Run 세 명사, 착수 순서 = Surface 먼저 | 2026-09-01 | **`src/`는 이 문서로 인해 한 줄도 움직이지 않았다** (그 문서 자신의 상태 줄) |

그리고 **아키텍처 §17이 소유자 진술 10개를 대조해 넷을 "없음", 둘을 "어긋남"으로 판정했다.** 그
여섯은 위 표의 미착수와 같은 것이다.

**따라서 이 문서의 제안은 "무엇을 새로 진단할까"가 아니라 "이미 결정된 것 중 무엇부터, 어떤
순서로, 어디까지"다.** 그리고 세 명사가 **덮지 않는** 실환경 결함 다섯을 §3에 따로 세운다 —
그것들은 이 디렉터리의 어느 문서에도, `docs/issues/`의 어느 파일에도 없다.

**척추는 여전히 건드릴 대상이 아니다.** `optimize`, `plan_orders`, `Account.prepare_fill`,
`Fill.__post_init__`, `ModelWindow`의 requirement 검사, 네 개의 시계, PIT 술어. 선행 문서 두 개가
같은 결론을 냈고 이 평가도 같다.

---

## 1. 오늘 직접 잰 것

선행 문서들이 지표로 삼은 값을 `develop @ 1ec2b8d7`에서 다시 쟀다. **셋은 목표에 도달했고,
셋은 안 했다.**

| 지표 | 2026-08-31 목표 | 오늘 | |
|---|---|---|---|
| `_internal/*_bridge.py` 총량 | 0 | **287** (`strategy_bridge.py` 하나) | 진행 |
| 두 번째 영속 저장소 (`catalog.json`) | 삭제 | **삭제됨** | ✅ |
| lint | clean | **clean** | ✅ |
| `src/` 안의 진짜 `vqapr.public` import | 0 | **CLI 3 + 출하 sample 2**, 나머지는 docstring 인용과 template 문자열 | ✅ 실질 달성 |
| 락 구현 수 | 1 | **2** — `_internal/filelock.py`(RMW mutex)와 `run_records.py:510`(heartbeat로 붙잡는 run-id lease). **다른 동물이다**; 부채가 아니라 사실로 적어야 한다 | 재분류 |
| god module | 관측값으로만 | `flow/simulation.py` **2,144** · `workspace.py` **1,548** · `data/scan.py` 1,318 · `flow/materialize.py` 1,316 | Step 4.1 / 5 미착수 |
| `SimulationFlow._execute_due` | 절단선 넷을 각자 파일로 | **284줄**, `SimulationFlow`는 ~1,750줄 / ~50 메서드 | 미착수 |

**추가로 확인한 두 가지 사실.**

**(a) 같은 이름 다른 클래스가 다섯 쌍 남아 있다.** 설치본에서 직접 확인:

```
DataModel · StrategyModel · Constraint · ConstraintBounds · ConstraintFinding
    vqapr.public.<X> is vqapr.authoring.<X>  ->  False   (다섯 전부)
CalendarLookback · RowsLookback · DatasetInput · Hold · Rebalance · StrategyResult
                                             ->  True    (record 126이 닫은 자리)
```

**(b) 로컬 트리에서 boundary test 하나가 실패하고 있었다.** `_internal/extensions/`가 record
`110` 이후 삭제됐는데 **stale `__pycache__` 디렉터리가 남아** `test_internal_holds_no_extension_authority`
가 `Path.exists()`로 걸렸다. 제거했고 boundary 37개 전부 통과한다. 다만 **그 테스트가 디렉터리
존재를 보므로, record `110` 이전 트리를 가진 사람은 누구나 red로 시작한다** — `.py`가 있는지를
봐야 한다. 한 줄 고칠 값어치가 있다.

---

## 2. 문제 — 세 층, 그리고 각각이 몇 개의 증상을 만드는가

### 2.1 층 1 — 저자 표면이 둘이다 (명사 2 · Surface)

**가장 비싸고, 가장 싸게 갚을 수 있고, 소유자가 이미 1순위로 정했다.**

오늘 `src/`는 같은 세 확장점을 두 번 정의한다.

```
authoring.py            915   ABC -> DataModel(inputs, output, compute(DataCall) -> DerivedRow)
                              ABC -> StrategyModel(inputs, account_history, diagnostics,
                                                   decide(StrategyCall) -> StrategyResult)
                              ABC -> Constraint, ConstraintBounds, ConstraintFinding
models/ + constraints/  ~450  Model -> DataModel(inputs, compute(DataModelContext) -> Rows)
                              Model -> StrategyModel(inputs, tables, account_requirements,
                                                     on_occurrence(StrategyModelContext) -> Hold|Rebalance)
_internal/models/agent_first.py 499   저자 protocol -> 엔진 호출 경계
_internal/strategy_bridge.py    287   StrategyModelContext -> StrategyCall
```

`strategy_bridge.py`의 docstring이 자기 소멸 조건을 적어 두었다: *"Two capability surfaces over
the same data. That is the next convergence, and when it lands this file has nothing left to do."*

**이것이 만드는 사용자 가시 결함 세 개** — 전부 오늘 재확인했다.

1. **loader가 세 확장점 중 하나만 authoring 계약을 받는다.** `load_strategy_model`은
   `_adapt_authored_strategy`로 감싸 준다. `load_data_model`과 `load_constraint`에는 대응물이
   없고, 거절 메시지가 *"make the registered object a subclass of
   `vqapr.constraints.constraint.Constraint`"* 라고 말한다 — **프레임워크가 방금 쓰라고 emit한
   모듈이 틀렸다고 말하는 것이다.** (post-step-07 R5)
2. **scaffold 셋이 표면 둘을 emit한다.** `new strategy` → `from vqapr import authoring as va` /
   `decide(self, call)` / `call.read("prices")`. `new datamodel` → `from vqapr.public import
   DataModel, DataRequirement` / `requirements()` / `context.window.observations(...)`.
   **후자는 record `128`이 호환을 위해 남겨 둔 옛 shape인데, scaffold가 그것을 가르친다.**
   한 프로젝트에 세 component를 scaffold한 저자는 import 관용구 두 벌을 갖는다. (R6)
3. **`SKILL.md:99`가 여전히 *"Both are authored the same way"* 라고 적는다.** 이 이슈의 이름이
   된 그 문장이다.

**어디까지가 이 층인가.** `docs/design/the-panel-the-surface-and-the-run.md` §3이 목표 shape다.
완료 조건은 세 줄이다 — `public.DataModel is authoring.DataModel`이 참, scaffold 셋이 같은 import와
같은 read 동사를 emit, `strategy_bridge.py`와 `agent_first.py` 삭제. **`SKILL.md`의 문장은 그때
고치는 것이 아니라 그때 참이 된다.**

### 2.2 층 2 — 데이터가 evaluation마다 파일에서 다시 온다 (명사 1 · Panel)

**측정된 값 하나가 이 층 전체를 말한다: 같은 모델, 같은 출력, 806.61s 대 1.31s. `compute`는
양쪽 다 0.36s.** 연산이 1.9%이고 데이터를 옮기는 것이 98%다 (`docs/issues/049`).

캠페인이 레인 A·B·C를 병합해 세 곱셈 인자 중 둘을 걷어냈다. **남은 것은 구조다** — 선언과 창
사이에 **표가 없다.** `ScanSession`은 커넥션·footer·instant grid·증명된 하한을 run 수명 동안
보관하지만 **행은 보관하지 않는다.** `DuckDbObservationStore.query`가 requirement 하나 ×
evaluation 하나마다 parquet에 SQL을 다시 보낸다. 창을 옮기는 것이 아니라 **매번 다시 자른다.**

이 층이 닫으면 §17의 1.1 · 1.2 · 1.3 · 1.4 · 9 · 10과 이슈 `035` · `045` · `046`이 **하나의
변경으로** 같이 닫힌다. `docs/design/...` §2가 그 설계다.

**여기 걸린 열린 결정 하나를 이 평가가 확인했다.** `035`의 columnar accessor는 *"레인 C 병합 후
재측정하고 그때 정한다"*로 미뤄져 있었다. **레인 C는 `df571533`로 병합됐다.** 즉 그 조건은
충족됐고, 아무것도 기다리고 있지 않다. 다만 지금 그것을 **accessor 변경으로** 열면 곧
`Panel`이 될 경로에 답하는 것이 되므로, 설계 문서 §2.3의 판단(*"panel이 이미 columnar이므로
035는 새 작업이 아니라 panel을 노출하는 것"*)을 따르는 편이 옳다.

**그리고 레인 D가 아직 시작되지 않았다.** `git worktree list`에 메인 트리 하나뿐이고
`qlibx-wt-046a`가 없다. `models/calls.py::declared_rows`가 여전히 field마다 한 번씩 읽고 Python에서
`(available_at, instrument)`로 join한다. **`049`가 존재하는 이유인 최종 측정이 여기 걸려 있다.**

### 2.3 층 3 — "run"이라는 한 단어가 세 가지 일을 한다 (명사 3 · Run)

실험 설정, 시험 대상 전략, 한 번의 실행 기록. §17의 3 · 3.1 · 3.2 · 4 · 5 · 5.1 · 6이 전부 그
겹침의 증상이다. 오늘 재확인한 사실:

- `RunDefinition.strategy`와 `FrozenRun.strategy`는 **단수**다. 한 run = 한 전략은 관례가 아니라
  dataclass 필드다.
- `_RUN_FIELDS`가 record에 남기는 것은 `run_id · account · tables · contract · source_digest ·
  declared_digest · roster · period`. **instruments 없음, strategy component id 없음, strategy 파일
  경로 없음, execution input id 없음**(=`034`).
- 삭제 verb가 없다 (`cli/run.py:385`가 직접 그렇게 적어 두었다). 안전하게 지우는 기계
  (`RunRecordWriter._clear`, heartbeat, lock)는 이미 있고 **부르는 것이 없다.**
- `vqapr list runs --id`는 run id **부분문자열 하나**다.

설계는 `docs/design/...` §4에 있고 `040`이 전제조건이다.

---

## 3. 세 명사가 덮지 않는 것 — 실환경 다섯, 어느 이슈 파일에도 없다

**`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md` (2026-08-31)**는 FF5+MOM factor
12 book과 residual 2벌을 **실제로 끝까지 만든** 세션의 기록이다. 지금까지 나온 어떤 testbed보다
규모가 크고, 그 발견의 절반이 `docs/issues/`에 없다. 아래 다섯은 오늘 코드에서 직접 확인했다.

### 3.1 여러 항목을 담은 선언 파일의 등록이 원자적이지 않다 🔴

**그 세션에서 가장 비쌌던 항목이고, 세 명사 중 어느 것도 이것을 닫지 않는다.**

`declarations.py::_apply`가 섹션을 순회하며 항목마다 **따로** 등록한다:

```python
for dataset_id, body in section("datasets").items():
    register_dataset(project_root, registration, source)     # 자기 lock + 전체 read-modify-write
for input_id, body in section("execution_inputs").items():
    register_execution_input(...)                            # 또 한 번
for agenda_id, body in section("agendas").items():
    Workspace.create(project_root).register_agenda(...)      # 또 한 번
...
```

k번째에서 거절되면 **1..k-1은 등록된 채로 남는다.** 등록은 immutable이므로 수정본을 다시 넣으면
이번엔 첫 항목이 conflict를 낸다. **복구 경로가 워크스페이스 전체 삭제밖에 없다.** 그 세션에서
이 루프가 반복됐고, 한 번에 `annual-fundamentals` 재산출 20분 + `momentum-signal` 8분을 물었다.

부수적으로: dataset 27개를 담은 문서는 workspace lock·read·write 사이클을 **27번** 돈다.

**닫는 모양.** 문서 하나가 한 트랜잭션이다 — 전부 검증한 뒤 lock 한 번 안에서 한 번 쓴다.
`_internal/atomic.py`와 `_internal/filelock.py`가 이미 그 기계를 갖고 있다.

### 3.2 run 기록이 메모리에 전부 쌓였다가 끝에 한 번에 쓰인다 🔴

측정치: **19GB / 12 run.** broad book 하나가 3GB 안팎이고, 실제로 읽히는 것은 `_ACCOUNT` 행
**0.07%**다.

**소스 자신이 이것을 적어 두었다** — `flow/run_records.py:3`: *"`recorder_rows` lives in memory for
the whole run. A run that crashes leaves..."*, `:23`: *"today's records are written in one pass at
the end."* `freeze_record`는 `flow.run()`이 **리턴한 뒤에** 호출되어
`result.final_state.recorder_rows`를 순회한다. 즉 2.6M 행짜리 book은 2.6M개 dict를 run 내내 힙에
들고 있다가 끝에 3GB JSONL을 쓴다. **중간에 죽으면 전부 없다.**

이것은 §2.2(Panel)와 **같은 뿌리가 아니다.** Panel은 읽기 측이고 이것은 쓰기 측이다. 그리고
Panel이 메모리를 더 쓰게 만드는 만큼 이쪽이 먼저 정리돼야 둘이 같은 프로세스에서 공존한다.

**닫는 모양.** (a) `append`가 이미 chunk를 받으므로 occurrence 경계에서 흘려보낸다. (b) position
행을 valuation마다 쓸지 선언하게 한다 — NAV만 필요한 소비자가 흔하다. (c) 포맷: §3.3을 보라.

### 3.3 프레임워크가 자기가 경고한 함정에 빠지는 포맷으로 출력을 낸다 🔴

vqapr은 입력의 timezone에 대단히 엄격하고 그 엄격함은 옳다. **그런데 출력은 JSONL이고, 그것을
읽는 가장 자연스러운 방법이 정확히 그 오류를 재생산한다:**

```
기록 안의 값        "2019-07-01T15:31:00+09:00"
read_json_auto   -> 2019-07-01 06:31        naive, 이미 UTC로 변환됨
CAST TIMESTAMPTZ -> 2019-07-01 06:31+09:00  ← 9시간 밀린 값. schema는 완벽하다
strptime %z      -> 2019-07-01 15:31+09:00  ← 맞는 값
```

그 세션은 실제로 9시간 밀린 factor 패널을 만들었고, **그 패널은 등록을 통과했다.** tz-aware이고
key도 unique하니까. 세션 날짜로 정렬하는 구조라 결과는 안 바뀌었지만, instant로 정렬하는
소비자가 있었으면 **조용한 look-ahead**였다.

그리고 그 우회를 강요한 것은 프레임워크다 — `vqapr show run --table vqapr.account --limit 0`이
26만~260만 행 JSON을 stdout으로 내므로 쓸 수 없고, 그래서 JSONL을 직접 읽게 된다.

**닫는 모양.** 기록을 parquet으로 내면 tz가 스키마에 실려 이 함정이 **사라진다** — §3.2의 크기
문제와 같은 해법이다. 또는 `vqapr.public`에 기록 reader를 노출한다. 둘 중 하나는 있어야 한다.

### 3.4 등록이 id는 지키는데 그 id가 가리키는 바이트는 안 지킨다 🟠

| | |
|---|---|
| 같은 id를 다른 선언으로 재등록 | **거부** |
| 등록된 id가 가리키는 parquet를 **그 자리에서 덮어쓰기** | **조용히 통과** |

run record는 `source_digest`를 담는다. **즉 run은 자기가 무엇을 읽었는지 아는데, dataset 등록은
자기가 무엇을 가리키는지 모른다.** 같은 개념이 한쪽에만 적용돼 있다. `docs/issues/023`은 이웃
이슈지만 같지 않다 — 023은 record의 digest 이야기이고 이것은 **등록에 digest가 없다**는 것이다.

### 3.5 쓰이지 않는 runtime dependency 넷 🟠

```
pyproject.toml dependencies:  cvxpy  duckdb  pandas  pyarrow  pydantic  pytz  pyyaml
src/vqapr 안의 import:         0      2       0*      7       0         0     4
                                                  * 주석과 docstring에만 등장
```

**`cvxpy` · `pandas` · `pydantic` · `pytz`가 어디서도 import되지 않는다.** `uv add vqapr`을 하는
모든 사람이 solver 스택과 pandas 3을 받는다. 2026-08-18 리뷰의 OS-2가 이것이고, 그때보다
악화되지도 개선되지도 않은 채 그대로다. **가장 싼 항목이다.**

### 3.6 그리고 이미 파일이 있는 가장 싼 것 — `047`

`data/scan.py`의 두 connection factory가 duckdb progress bar를 끄지 않아, 느린 명령의 JSON
envelope에 carriage-return 프레임이 섞인다. **성공한 명령의 출력이 파싱되지 않는 유일한 열린
이슈다.** 두 줄.

---

## 4. 제안하는 순서

각 단계는 **`develop`이 green인 상태로** 들어가고, 하나의 implementation record를 남긴다.
캠페인 §4의 게이트 규칙(하한을 숫자로 박지 말고 분기한 커밋에서 직접 재라, `-rs`를 항상 붙여라)이
그대로 적용된다.

| # | 무엇 | 왜 여기 | 되돌리기 |
|---|---|---|---|
| **0** | **§3.5 unused deps · §3.6 `047` · §1(b) boundary test** | 하루치. 회귀 위험 0. 셋 다 사용자에게 바로 도달한다 | 자명 |
| **1** | **명사 2 — Surface** (`036`의 남은 다섯 행) | **소유자가 정한 1순위.** 다른 둘과 독립. `036` ruling은 이미 CONVERGE이고 절반이 이미 들어와 있다. 끝나면 `strategy_bridge`(287) + `agent_first`(499)가 삭제되고 R5·R6이 같이 닫힌다 | 중 |
| **2** | **§3.1 등록 트랜잭션** | 세 명사와 독립이고, **실환경에서 가장 비쌌던 항목**이다. 명사 3이 workspace 문서를 마이그레이션하기 **전에** 들어가야 한다 — 마이그레이션 중 부분 실패는 지금 복구 경로가 없다 | 하 |
| **3** | **§3.2 · §3.3 run 기록 — 흘려 쓰기와 포맷** | 명사 1이 메모리를 쓰기 시작하기 전에 쓰기 측 상주를 없앤다. 그리고 §3.3의 조용한 look-ahead는 **correctness**다 | 중 |
| **4** | **레인 D** (`046` 전반, 한 스캔이 여러 field) | 캠페인의 마지막 레인. `049`의 최종 측정이 여기 걸려 있고, **그 측정 없이는 명사 1의 이득을 잴 기준선이 없다** | 하 |
| **5** | **명사 1 — Panel** (`grain` 선언 + `PanelLookback`/`SeriesLookback` + 물질화) | 레인 D 이후. `035`가 여기서 같이 닫힌다. **`grain` 거절과 `RowsLookback` 의미 변경은 같은 릴리스에 같이 들어가야 하고 따로 나갈 수 없다** (설계 §2.4) | 상 |
| **6** | **`040`** (agenda 공유) | 명사 3의 전제. 작고 독립적 | 하 |
| **7** | **명사 3 — Run** (설정/기록 분리, strategy 축, `rm` verb, `034` 닫힘) | workspace 문서 마이그레이션이 걸리므로 마지막. §3.4도 여기서 같이 닫는 것이 자연스럽다 | 최상 |

**Step 4.1(`workspace.py` 분해)와 Step 5(`SimulationFlow` 분해)는 이 순서에 넣지 않았다.**
둘 다 선행 문서에 있고 여전히 유효하지만, **위 일곱이 그 두 파일을 어차피 다시 쓴다.** 명사 3이
`workspace.py`를 마이그레이션하고, 명사 1이 `scan.py`/`store.py`를 다시 쓴다. 먼저 쪼개면 같은
코드를 두 번 옮긴다. 크기는 §1처럼 관측값으로 계속 재되 지금 착수하지 않는다 (기록 `118`의
결정과 같은 취지다).

---

## 5. 하지 않을 것

- **척추.** `optimize`, `plan_orders`, `Account.prepare_fill`, `Fill.__post_init__`,
  `ModelWindow`의 requirement 검사, 네 개의 시계, frozen input, warm-up과 atomic callback
  acceptance. 세 개의 진단 문서가 전부 같은 결론이다.
- **PIT 규칙.** field는 표현식이지 statement가 아니다 — **look-ahead가 문법으로 막힌다는 성질을
  건드리지 않는다.**
- **docstring을 줄이지 않는다.** 이 저장소의 docstring은 결정의 근거 기록이다. 코드를 옮길 때
  근거도 같이 옮긴다.
- **닫힌 이슈 파일을 옮기지 않는다.** `src/`의 103곳과 `docs/`의 154곳이 이 번호를 인용한다.
  색인은 `docs/issues/README.md`가 진다.
- **backward compatibility를 지키기 위해 shape를 둘로 두지 않는다.** Step 1과 Step 5는 각각
  showcase와 testbed를 깬다. **깨는 것이 목적에 부합한다** — 설계 문서 §2.4가 그 근거를 적어
  두었다: 조용히 뜻이 바뀌는 경로를 하나도 남기지 않는 유일한 장치가 저자가 한 번 손으로
  편집하는 것이다.

---

## 6. Testbed 대조 — 발견이 반영되어 있는가

| testbed | 최근 | 반영 상태 |
|---|---|---|
| `kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md` | 2026-08-31, 실사용 최대 규모 | **A2는 `040`으로 반영됨. A1·A3·A4·A5·A6·A7·B1·C3·C4·C5·E1·E2는 `docs/issues/`에 대응 파일이 없다.** 그중 다섯을 §3에 세웠다 |
| `kwam-enhanced-index/vqapr-final-testbed/` | 2026-08-31, **0.2.0a2에 armed, 아직 안 돌았다** | `KNOWN-ISSUES.md`가 10개를 싣고 있는데 **그중 넷(`030`·`032`·`038`·`043`)이 develop에서 이미 닫혔다.** 그 파일 자신의 규칙이 *"the list must be exactly the open set"*이고, 닫힌 항목이 남아 있으면 **진짜 finding을 억누른다.** 다음 run 전에 wheel 재빌드 + 목록 재생성이 필요하다 |
| `kwam-enhanced-index/vqapr-testbed-3/` | 2026-08-31, TASK만 있고 FINDINGS는 template | 미실행 |
| `kwam-enhanced-index/vqapr-testbed`, `-2` | 2026-08-24~25 | 그 시점 발견은 `011`~`033`으로 흡수됨 |
| `kaist-thesis/vqapr-testbed/FRICTION-F.md` | 2026-08-24 | F-001~F-007이 record `055`로 대부분 닫힘. **F-003·F-004(Exchange scaffold 없음, `KrxExchange` 객체가 직접 등록 불가)는 "public interface 재설계 대기"로 의도적으로 열어 둔 상태** — 그 재설계가 **명사 2다.** Step 1의 완료 조건에 넣을 값어치가 있다 |

**캠페인 문서가 가리키는 `kwam-enhanced-index/vqapr-performance-testbed/`는 존재하지 않는다.**
`049`의 재현 하네스(`wide_experiment.py`, `pivot_experiment.py`, `bench.py`)를 그 경로에서
찾으라고 두 문서가 적고 있으므로, Step 4/5 착수 전에 **실제 경로를 확인해 두 문서를 고쳐야
한다.** 캠페인 §4의 경고("testbed의 `probes.py`가 develop과 어긋나 있었다, 고치기 전에는 모든
측정이 `AttributeError`로 죽는다")와 같은 자리다.

---

## 7. 게이트

| 게이트 | 명령 |
|---|---|
| lint | `uv run ruff check src/` |
| fast | `PYTHONUTF8=1 uv run pytest tests/ -q -rs` — **분기한 커밋에서 직접 잰 값과 비교**, `-rs` 필수 |
| full incl. slow | `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` — Step 1·3·5·7 필수 |
| surface (Step 1 전용) | `public.<X> is authoring.<X>`가 다섯 쌍 전부 참, scaffold 셋이 같은 import를 emit, `_internal/`에 bridge 0 |
| cost (Step 4·5 전용) | `049`의 anti-join을 **타이밍보다 먼저** 돌린다. 600배 빠르면서 조금 다른 materialization은 빠른 모델이 아니라 **다른 모델**이다 |

---

## 8. gjc ultragoal이 blocked로 남긴 것 — 무엇이, 왜, 그리고 지금은 어떤가

**두 번의 ultragoal run이 있었고 둘 다 끝나지 않았다.** durable state는
`gjc-handoff/session-01/goals.json`, `gjc-handoff/session-03/goals.json`,
`../kwam-enhanced-index/gjc-handoff/session-state/`에 남아 있다.

| run | 종료 상태 |
|---|---|
| session-01 (`01a031f9`, 08-24) | `G001` complete, **`G002` active**, `G003`~`G005` pending. 오너가 G002 진행 중 종료 |
| session-03 (`01a03479`, 08-24~25) | `G001`~`G004`·`G009` complete, `G005`·`G006`·`G007` superseded, **`G008` blocked**, **`G010` active**, **`G011` pending** |

### 8.1 `G008` — 유일한 blocked. 두 개의 게이트, 그리고 뒤집힌 전제

`G008` = *"Hard-remove the old qlibx API"*: `vqapr.public`을 삭제하고
`{flow,data,account,evidence,orders,valuation,constraints}`를 `vqapr._internal` 밑으로 물리
이동(측정치 **38 files / 8,139 lines / 70 inbound references**)한 뒤 breaking `0.2.0a1`을 낸다.

ledger가 적은 차단 사유 두 개는 **둘 다 정당했다.**

1. **PLAN GATE.** 승인된 계획의 escalation gate — *"whole testbed — including `register.py` —
   passes T0 trace/row comparator"* — 가 `G010`의 산출물인데 **끝내 돌지 않았다.** 게다가 T4를
   먼저 시작하면 parity 비교가 돌아야 할 legacy 경로 자체를 파괴한다 (T2가 그것을 *"solely for
   baseline comparison"*으로 살려 두고 있었다).
2. **OWNER APPROVAL.** *"Deletion is revertible; a release is not."* 이 run의 나머지는 전부
   되돌릴 수 있었고 이것만 아니었다.

여기에 **계획 자신의 권한 모순**이 얹혀 있었다 — Approval State는 *"authorizes no source
mutation"*이라 하고, ordered step 10은 *"stop pending approval before commit/tag/push/release"*라
한다. terminal critic이 step 10을 controlling으로 판정했고 (근거: 오너의 standing constraint가
금지한 것은 정확히 다섯 개의 git 동작이고 source mutation은 거기 없다, 오너가 `d23ca03`을
revert하지 않고 commit했다), **그 판단은 되돌릴 수 있는 작업에는 쌌지만 여기서는 싸지 않았다.**

**핵심은 여기다: `G008`은 풀린 적이 없다. 나흘 뒤에 전제가 뒤집혀서 무효가 됐다.**

```
08-24  G008 작성       "vqapr.public이 legacy, project.py/Project workflow가 목적지"
08-28  PEP 669 tracer  완주하는 CLI journey에서 project.py 619줄 중 실행 0줄,
                       simulation.py 327줄 중 0줄, 모든 bridge 0줄.
                       그 클러스터는 자기를 위해 쓰인 테스트만 실행한다.
                       vqapr.public은 shipped 경로 전부에 있다.
09-01  record 104      "shipped vqapr.public이 살아남는다. project.py가 죽는다"
09-01  record 124      반대편 삭제 — 13 modules / 4,001 lines
```

즉 **`G008`이 지우려던 것이 실제로 출하되는 것이었고, 목적지라던 것이 한 줄도 실행되지 않는
것이었다.** record 124가 그 사실을 명시한다: *"That is the opposite direction, written on
2026-08-24 — four days before the trace that inverted the finding."*

> **그런데 문서는 아직 그렇게 읽히지 않는다.** `docs/design/agent-first-surface.md`의
> **"## The G008 admission conditions"** 절이 여전히 *"a future session may open `G008` only when
> both hold …"*라고 적고, 두 게이트를 열린 조건으로 기술한다. record `098`·`105`·`124` 셋이 그
> 문장을 두고 서로 다른 말을 한다. **다음 세션이 그 절을 읽고 `vqapr.public`을 지우려 들 수
> 있다.** Step 0에 넣어야 할 항목이다 — 게이트를 여는 것이 아니라 **반대 방향으로 닫혔다고
> 적는 것**이다.

### 8.2 blocked였다가 superseded된 둘

`G006`(testbed parity)와 `G007`(dogfooding)은 둘 다 *"Project.materialize가 출력을 저장하지
않고 Project.simulate가 존재하지 않는다"*로 blocked였다. `G009`가 그것을 해소하자 두 goal의
scope가 `G010`으로 합쳐지며 superseded됐다. **그 `G010`이 지금까지 `active`다.**

### 8.3 `G011` — 시작조차 되지 않은 goal이 오늘의 1순위다

> *"Settle the agent-first surface design before migrating further callers — 세 개의 열린 질문을
> 오너와 답한 뒤 남은 6개 src legacy consumer와 5개 showcase를 확정된 설계에 맞춰 옮긴다."*

status: `pending`. **이것이 명사 2이고 `docs/issues/036`이다.** 오너가 `G010`을 멈추고 만든
goal이며, 그 이유가 steering에 그대로 적혀 있다: *"The owner stopped this work to redesign the
surface from the caller inward rather than keep migrating callers onto a shape under active
reconsideration."* 표면이 재고 중인데 소비자를 여섯 개 더 옮기지 말라는 것.

**일 년 전 판단이 아니라 지금도 유효한 판단이고, 그래서 §4의 Step 1이 그것이다.**

### 8.4 세 번의 실제 실패 — 무엇이 깨졌고 오늘은 어떤가

`gjc-handoff/README.md` §7이 *"같은 벽에 세 번째로 머리를 박지 마라"*고 적은 자리다. 오늘 트리에
대고 다시 확인했다.

| | 그때 | 오늘 |
|---|---|---|
| **7.1 scaffold 마이그레이션** (increment 24) | authoring contract 위로 다시 쓰자 **테스트 10개가 깨져 revert.** 원인: *"scaffold + CLI 등록 경로 + loader conformance check가 한 단위"* | **커플링은 그대로다.** 다만 동기의 절반은 사라졌다 — record `125`가 callback에서 intent 주조를 걷어내 strategy 템플릿에 `EconomicPortfolioIntent`가 없다. **대신 constraint 템플릿에 그대로 남아 있다** (`scaffold.py:176`이 `EconomicPortfolioIntent`를 import하고 `:238`의 `validate_intended`가 `intent.targets`를 순회한다). **없애려던 ceremony가 strategy에서 constraint로 옮겨 살아남았다** |
| **7.2 `agent/sample` 마이그레이션** (increment 41) | 7.1과 **똑같은 구조적 커플링**으로 깨끗이 revert | `reversal_5d.py`는 `vqapr.authoring`으로 옮겨졌다. `journey.py`는 여전히 `fingerprint_component(...)`를 손으로 계산하고 `RunDefinition`을 손으로 조립한다 — **그런데 record 104 이후 그게 옳은 방향이다.** 이 목표도 뒤집힌 전제 위에 있었다 |
| **7.3 showcase 병렬 배치** (increments 16–19, 29) | 두 번 revert. 워커 "완료" 보고 4건이 전부 거짓, showcase 6개가 각자 bare `models.py`를 만들어 **sys.path 선점 회귀**를 유발 | **교훈 셋 다 반영됐다.** bare `models.py` 없음 (`show001_models.py`, `show002_models.py`, `show004_models.py`로 접두), showcase 9개 전부 `vqapr.public` 위에 있고 (record 124가 001·002·004를 **G010이 원하던 것과 정반대로** 옮겼다), `show_009_authoring_contract`가 추가됐다 |
| **7.4 goal 기계가 `G010`을 놓지 않음** | `pause` 4회 + `drop` 1회 전부 거부 — *"an active story still has resolvable work"*. 원인: `G010`이 **증명 완료된 절반**(testbed parity)과 **차단된 절반**(dogfooding)을 한 goal에 묶고 있었다 | 같은 결함이 오늘 다른 규모로 있었다 — `docs/issues/036`의 헤더가 *"not yet implemented"*라고 적혀 있었는데 절반은 이미 구현돼 있었다. §정리 항목에서 고쳤다 |

### 8.5 이 실패들에서 가져갈 규칙 셋

1. **gjc는 능력이 아니라 순서에서 실패했다.** 세 번의 revert가 전부 *"단위가 slice보다 컸다"*다.
   그리고 그 실패가 만들어낸 **단 하나의 구조적 발견 — scaffold + CLI 등록 경로 + loader
   conformance가 한 단위 — 은 오늘도 참이다.** §4의 Step 1은 *"scaffold를 옮긴다"*가 아니라
   **그 단위 전체**로 잡아야 한다. 점진적으로 가면 두 번 증명된 방식으로 실패한다.
2. **계획이 나흘 동안 틀린 facade를 향해 있었고, 그것을 잡은 것은 코드 읽기가 아니라 실제 제품
   여정 위의 tracer였다.** Step 1 착수 전에 그 측정을 다시 한 번 돌릴 값어치가 있다 — 오늘 CLI가
   실제로 실행하는 표면이 무엇인지.
3. **완료된 절반과 차단된 절반을 한 goal에 묶지 마라.** 그 goal은 닫히지도, 멈추지도, 버려지지도
   않는다. `G010`이 그래서 아직 `active`이고, `036`의 헤더가 같은 이유로 하루 넘게 틀린 상태로
   있었다.

### 8.6 Step 0에 추가할 항목

- `docs/design/agent-first-surface.md`의 **"The G008 admission conditions"** 절을 **닫는다.**
  게이트를 여는 것이 아니라, record `104`/`124`가 그 goal을 **반대 방향으로 해소했고 두 게이트가
  이제 아무것도 보호하지 않는다**고 적는다. 지금은 세 record가 그 문장을 두고 서로 다른 말을
  하고, 문서 자신은 여전히 열린 게이트처럼 읽힌다.
- `gjc-handoff/README.md`에 한 줄: **§7.1·§7.2의 방향은 record 104/124로 뒤집혔다. §7의 실패
  분석은 유효하고 §8의 작업 순서는 무효다.** 그 파일은 지금 "다음 세션은 여기부터 읽는다"고
  적혀 있으므로, 고치지 않으면 다음 세션이 뒤집힌 계획을 이어받는다.
