# 수렴 캠페인 — 단계, 인수조건, 병합 순서

| | |
|---|---|
| **작성 시각** | 2026-09-02 KST (+09:00) |
| **기준 커밋** | `develop @ 1ec2b8d7`. 이 문서의 모든 경로와 수치는 그 커밋에서 직접 잰 것이다 |
| **트리 상태** | `pytest tests/ -q -rs` → **1292 passed, 14 deselected** · `ruff check src/` → clean |
| **진단** | `docs/diagnostics/2026-09-02-what-the-tree-owes-the-mental-model.md`. **이 문서는 그것을 재론하지 않는다** |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` → `docs/design/the-panel-the-surface-and-the-run.md` |
| **선행 캠페인** | `docs/refactoring/2026-09-01-the-read-path-campaign.md` — 레인 A·B·C 병합 완료, **레인 D 미착수**. 이 캠페인이 그것을 Step 4로 흡수한다 |
| **완료** | **2026-09-02, `develop @ d212bceb`.** Step 0–7 전부 병합 — records `129`(M0), `130`–`133`(M1), `134`(M2), `135`(M3), `136`(M4), `137`(M5), `138`(M6), `139`(M7). 마지막 게이트: ruff clean · fast **1314** / slow **13** · showcase **9/9**. 남은 것은 각 record의 "하지 않은 것"과 `docs/issues/README.md` §1(열린 넷)에 있다 |

> **이 캠페인은 새 진단을 하지 않는다.** 여덟 단계 전부가 **이미 내려진 소유자 ruling**이거나
> **이미 측정된 결함**이고, 이 문서가 더하는 것은 순서·단위·인수조건뿐이다. 무엇이 왜 문제인지는
> 진단 문서에 있다.

---

## 0. 왜 이 순서인가 — 세 개의 제약

**제약 1 — 단위는 gjc가 두 번 증명했다.**
`gjc-handoff/README.md` §7.1과 §7.2가 같은 벽에 두 번 부딪혀 revert했고, 원인을 정확히 적어 두었다:
*"scaffold는 혼자 마이그레이션할 수 없다. **scaffold + CLI 등록 경로 + loader conformance check가
한 단위**다."* Step 1은 그 단위 전체이며, 쪼개면 두 번 증명된 방식으로 실패한다.

**제약 2 — 되돌리기 비용이 뒤로 갈수록 커진다.**
Step 0~2는 되돌리기가 자명하다. Step 5(Panel)는 workspace 문서 마이그레이션을 동반하고, Step 7(Run)은
run 기록 레이아웃을 바꾼다. `2026-09-01` 캠페인 §6의 두 번째 위험 — *"마이그레이션 후 revert하면
모든 명령이 실패한다"* — 이 그대로 적용된다.

**제약 3 — 뒤에서 메모리를 쓰는 것이 앞에서 메모리를 놓아야 성립한다.**
Step 5는 panel을 프로세스에 상주시킨다. Step 3은 run 기록을 힙에서 내린다. **Step 3이 먼저다** —
같은 프로세스에서 둘이 공존해야 하기 때문이다.

```
Step 0  잡동사니        독립, 하루
   |
Step 1  Surface        <- 소유자 1순위. 다른 무엇과도 독립
   |
Step 2  등록 트랜잭션   <- Step 5/7의 문서 마이그레이션 전에 반드시
   |
Step 3  run 기록        <- Step 5가 메모리를 쓰기 전에
   |
Step 4  레인 D          <- Step 5의 측정 기준선
   |
Step 5  Panel          <- grain 거절 + RowsLookback 의미 변경, 분리 불가
   |
Step 6  040            <- Step 7의 전제
   |
Step 7  Run
```

**각 단계는 `develop`이 green인 상태로 들어간다.** 단계 하나 = implementation record 하나 =
`--no-ff` 병합 하나. `.agent/PLANS.md`의 ExecPlan은 Step 1·5·7에 대해 만든다(나머지는 bounded
inspect-edit-validate로 충분하다).

---

## Step 0 — 하루치, 회귀 위험 0

네 항목 전부 독립이고 서로를 기다리지 않는다. **셋은 사용자에게 바로 도달하고, 둘은 다음 세션이
잘못된 방향으로 가는 것을 막는다.**

| # | 무엇 | 접촉면 | 인수조건 |
|---|---|---|---|
| 0.1 | **안 쓰이는 runtime dependency 넷 제거** — `cvxpy`, `pandas`, `pydantic`, `pytz`. `src/vqapr` 어디서도 import되지 않는다(`pandas`는 주석과 docstring에만) | `pyproject.toml` | `uv sync` 후 전체 스위트 green. 넷 중 하나라도 실제로 필요하면 **그 import를 찾아 이 항목에서 빼고 이유를 적는다** |
| 0.2 | **`047` — duckdb progress bar를 끈다.** 느린 명령이 JSON envelope에 carriage-return 프레임을 섞는다 | `data/scan.py`의 두 connection factory (`_open`, `ScanSession.connection`) | 큰 source를 등록하는 명령의 stdout이 **순수 JSON으로 파싱된다**는 테스트. `047`을 CLOSED로 |
| 0.3 | **boundary test가 디렉터리가 아니라 모듈을 본다** | `tests/boundaries/test_internal_holds_no_extension_authority.py` | `_internal/extensions/`에 `__pycache__`만 있어도 통과하고, `.py`가 하나라도 있으면 실패한다. **record `110` 이전 트리를 가진 사람이 red로 시작하지 않는다** |
| 0.4 | **뒤집힌 두 문서를 닫는다** | `docs/design/agent-first-surface.md`의 "The G008 admission conditions" 절, `gjc-handoff/README.md` | G008 절이 *"a future session may open G008 only when…"* 대신 **record `104`/`124`가 반대 방향으로 해소했고 두 게이트가 이제 아무것도 보호하지 않는다**고 적는다. `gjc-handoff/README.md`(= `.agent/project.yaml`의 `session_handoff`, 즉 **canonical**)에 *"§7의 실패 분석은 유효, §8의 작업 순서는 무효"* 한 줄 |

> **0.4를 뒤로 미루지 마라.** 두 문서 다 *"다음 세션은 여기부터 읽는다"*로 지목되어 있고, 지금
> 상태로는 다음 세션이 `vqapr.public`을 지우러 간다. 진단 §8이 그 경위다.

---

## Step 1 — Surface: 저자 표면을 하나로 (`036`, R5, R6, `G011`)

**소유자가 착수 1순위로 정했다** (`docs/design/the-panel-the-surface-and-the-run.md` §6). `036`의
ruling은 2026-08-31 CONVERGE이고 **절반은 이미 들어와 있다**(records `126`, `128`).

### 진입조건

Step 0.3·0.4 완료. 다른 것은 없다 — 이 단계는 Panel·Run과 완전히 독립이다.

### 하나의 단위 — 쪼개지 않는다

```
authoring.py                          915   세 확장점의 두 번째 정의
constraints/constraint.py · models/   ~450   첫 번째 정의
_internal/models/agent_first.py       499   저자 protocol -> 엔진 호출 경계
_internal/strategy_bridge.py          287   StrategyModelContext -> StrategyCall
extension/loading.py                        load_data_model:274 · load_strategy_model:296
                                            _adapt_authored_strategy:319 · load_constraint:349
extension/scaffold.py                       _STRATEGY_TEMPLATE:17 · _DATA_MODEL_TEMPLATE:59
                                            _CONSTRAINT_TEMPLATE:159
testing/conformance/runner.py               _CONTRACTS:69-83 · _LOADERS:93-96
agent/skill/SKILL.md:99                     "Both are authored the same way"
```

**이 여덟이 한 단위다.** gjc가 scaffold만, 그 다음 `agent/sample`만 옮겨 보고 두 번 revert했고,
그 실패에서 나온 유일한 구조적 발견이 이것이다.

### 목표 형태

`docs/design/the-panel-the-surface-and-the-run.md` §3. 요약하면:

- **`vqapr.authoring`이 저자 표면이다.** `vqapr.public`은 **동사**(등록·실행·분석)를 갖고 authoring의
  이름을 **동일 객체로** 재수출한다.
- 공통 `Model` base에서 `DataModel`(account 없음)과 `StrategyModel`(account 있음, venue 통과)이
  나온다. **그 차이가 클래스 차이의 전부**다.
- `Constraint`도 같은 문으로 들어온다. **오늘 constraint 템플릿은 저자에게
  `EconomicPortfolioIntent`를 건네고 `intent.targets`를 순회하게 한다**(`scaffold.py:176`, `:238`) —
  record `125`가 strategy 쪽에서 걷어낸 바로 그 ceremony가 여기 살아남았다. 같이 걷어낸다.

### 인수조건

1. **다섯 쌍이 같은 객체다.**
   ```python
   for n in ("DataModel","StrategyModel","Constraint","ConstraintBounds","ConstraintFinding"):
       assert getattr(public, n) is getattr(authoring, n)
   ```
   **테스트로 고정한다** — 오늘 다섯 전부 `False`다.
2. **scaffold 셋이 같은 문법을 emit한다** — 같은 import 줄, 같은 선언 메서드(`inputs()`), 같은 read
   동사(`call.read(alias)` / `context.read(alias)`), 같은 행 타입(`Observation`). 세 템플릿을 emit해
   **수정 없이 등록하고 돌리는** 테스트(오늘의 `tests/extension/test_scaffold_runs_unedited.py`를 세
   kind로 확장).
3. **loader가 세 확장점 모두에서 같은 계약을 받는다.** `_adapt_authored_strategy`의 대응물이
   생기거나, 셋 다 필요 없어진다. **후자가 목표다** — 계보가 하나면 adapt할 것이 없다.
4. **`_internal/strategy_bridge.py`와 `_internal/models/agent_first.py`가 삭제된다.**
   `_internal/`에 남는 것은 `atomic.py`, `filelock.py`뿐. `strategy_bridge`의 docstring이 적어 둔
   자기 소멸 조건이 그것이다.
5. **`SKILL.md:99`의 문장이 참이 된다.** 문장을 고치는 것이 아니다 — 그게 이 issue의 이름이다.
6. **깨진 showcase를 고친다, 우회하지 않는다.** showcase 9개 전부 `vqapr.public` 위에 있고
   `show_009`는 authoring 계약 자체를 시연한다. 재수출이 동일 객체면 대부분 그대로 돌아야 하고,
   안 도는 것은 **계보가 실제로 갈려 있던 자리**이므로 그 자리가 이 단계의 산출물이다.
7. `test_all` (slow 13개 포함) green.

### 이 단계가 깨는 것

**testbed와 showcase의 backward compatibility를 깬다. 그것이 목적이다.** 두 계보가 공존하는
릴리스를 하나 두면 저자가 어느 쪽을 상속했는지에 따라 다르게 동작하고, `036`이 측정한 비용이
그대로 다시 발생한다.

### 되돌리기

중. 순수 소스 변경이고 workspace 문서도 run 기록도 건드리지 않는다. 되돌리기는 브랜치 revert 하나.

---

## Step 2 — 선언 파일 하나가 한 트랜잭션 (실환경 A3, 이슈 파일 없음)

### 왜 여기인가

**Step 5와 Step 7이 workspace 문서를 마이그레이션한다. 그 마이그레이션 중 부분 실패는 지금 복구
경로가 없다.** 그리고 이것은 실사용에서 가장 비쌌던 결함이다 — 선언 파일의 오타 하나가
`.vqapr/` 전체 삭제 + 재산출 28분으로 이어지는 루프가 반복됐다.

### 오늘의 사실

`declarations.py::_apply`가 섹션을 순회하며 **항목마다** `Workspace.create(...).register_*()`를
따로 부르고, 각각이 자기 lock + 전체 read-modify-write 사이클을 돈다. k번째에서 거절되면
1..k-1은 등록된 채로 남고, 등록은 immutable이므로 수정본 재등록이 첫 항목에서 conflict를 낸다.
dataset 27개짜리 문서는 lock·read·write를 **27번** 돈다.

### 무엇

- `_apply`가 **전부 검증한 뒤 lock 하나 안에서 한 번 쓴다.** 기계는 이미 있다 —
  `_internal/filelock.exclusive`와 `_internal/atomic.write_atomically`.
- **섹션 간 의존은 이미 순서로 풀려 있다**(`_apply`가 dependency order로 돈다). 트랜잭션은 그
  순서를 바꾸지 않고 커밋 지점만 옮긴다.

### 인수조건

- **k번째 항목에서 거절되는 문서를 등록하면 workspace가 등록 전과 byte-identical이다.** 이것이
  이 단계의 유일한 인수조건이고, 테스트가 그것을 직접 단언한다.
- 유효한 문서 하나의 등록이 workspace를 **한 번** 쓴다(쓰기 횟수를 세는 테스트).
- 기존 등록 스위트 전부 green — **오늘 통과하는 선언은 하나도 안 깨져야 한다.**

### 되돌리기

하. 커밋 지점만 옮기는 변경이고 문서 shape를 바꾸지 않는다.

---

## Step 3 — run 기록: 흘려 쓰기와 포맷 (실환경 A4·A5·A6, 이슈 파일 없음)

### 왜 여기인가

Step 5가 panel을 프로세스에 상주시키기 **전에** 쓰기 측 상주를 없앤다. 그리고 A5는
**correctness**다 — 지금 프레임워크는 자기가 길게 경고한 tz 함정에 빠지는 포맷으로 출력을 낸다.

### 오늘의 사실

소스가 스스로 적어 두었다 — `flow/run_records.py:3`: *"`recorder_rows` lives in memory for the
whole run"*, `:23`: *"today's records are written in one pass at the end."* `freeze_record`는
`flow.run()`이 리턴한 **뒤에** `result.final_state.recorder_rows`를 순회한다. 2.6M 행짜리 book은
2.6M dict를 run 내내 힙에 들고 있다가 3GB JSONL을 쓴다. 측정치 **19GB / 12 run**, 실제로 읽히는
것은 `_ACCOUNT` 행 **0.07%**.

읽는 쪽: `read_json_auto`가 `"2019-07-01T15:31:00+09:00"`를 **9시간 밀린** tz-aware 값으로 만들고,
그 패널이 등록을 통과한다. 그 우회를 강요한 것은 `vqapr show run`이 26만~260만 행 JSON을 stdout
으로 내기 때문이다.

### 무엇 (세 갈래, 한 단계)

1. **흘려 쓴다.** `RunRecordWriter.append`가 이미 chunk를 받으므로 occurrence 경계에서 넘긴다.
   `record.json`이 마지막에 쓰이는 것은 유지한다 — *"`record.json` 존재가 완료의 표식"*이라는
   `flow/records.py`의 계약은 옳고 이 변경이 그것을 강화한다(죽은 run은 rows만 남는다).
2. **포맷.** 기록을 parquet으로 내면 tz가 스키마에 실려 A5가 **사라진다**. JSONL을 유지한다면
   `vqapr.public`에 기록 reader를 노출하는 것이 최소 대안이다. **둘 중 하나는 있어야 한다.**
3. **position 행을 매 valuation마다 쓸지 선언하게 한다.** NAV만 필요한 소비자가 흔하고, 그것이
   0.07%의 나머지다.

### 인수조건

- **run이 도는 동안 `tables/`의 파일 크기가 증가한다**(중간 관찰 가능).
- **run 중간에 프로세스를 kill하면 그때까지의 rows가 디스크에 있고 `record.json`은 없다** —
  `run_ids`가 그것을 완료된 run으로 세지 않는다.
- 힙 상주가 사라진 것을 **행 수 × 상수가 아니라 실측 RSS로** 확인한다.
- **`show run`이 큰 표를 필터해서 낼 수 있다**(예: `--instrument _ACCOUNT`), 또는 기록 파일 경로가
  공식 계약으로 문서화된다.
- 기록 포맷을 바꾸면 **`analysis/performance.py::nav_series`와 기존 run 기록 읽기 경로가 모두
  green**이고, 이전 shape를 한 릴리스 동안 읽을 수 있다.

### 되돌리기

중. 포맷을 바꾸면 이전 run 기록의 읽기 경로를 남겨야 한다.

---

## Step 4 — 레인 D: 한 스캔이 여러 field를 만족시킨다 (`046` 전반)

`docs/refactoring/2026-09-01-the-read-path-campaign.md`의 마지막 미착수 레인이다. 그 문서의 레인
D 절이 계약이고, 여기서는 **왜 이 순서인지만** 적는다.

**Step 5의 이득을 잴 기준선이 여기 걸려 있다.** `049`가 존재하는 이유인 최종 측정 — 806.61s
대비 — 이 레인 D 이후에 나온다. 그 숫자 없이 Panel을 넣으면 **무엇이 얼마나 좋아졌는지 말할 수
없다.**

오늘의 사실: `models/calls.py::declared_rows`가 alias 하나의 field마다 한 번씩
`window.observations(requirement)`를 호출하고 Python에서 `(available_at, instrument)`로 join한다.

**인수조건은 캠페인이 정한 그대로다:** `ff_factors`의 선언된 입력 3개가 스캔 **3 → 1**. 더해서,
그 캠페인 §4의 세 가지 측정 차단 요인(testbed `probes.py` 동기화, `+inf` 82행, wall-time 흔들림)을
**측정 전에** 확인한다.

> **경로 하나를 먼저 고쳐야 한다.** 캠페인 문서와 `docs/issues/archive/047`이 재현 하네스를
> `kwam-enhanced-index/vqapr-performance-testbed/`에서 찾으라고 적는데 **그 디렉터리는 존재하지
> 않는다.** 실제 경로를 확인해 두 문서를 고치는 것이 이 단계의 첫 작업이다.
>
> **확인함 (기록 `136`).** 실제 경로는 없다 — 하네스 파일 넷 중 어느 것도 `kwam-enhanced-index/` 아래에 없다.
> 두 문서에 그 사실을 적었다. Step 5의 기준선은 806.61s가 아니라 Step 5가 착수할 때 그 시점의 트리에서
> 직접 재는 숫자여야 한다.

### 되돌리기

하. 쿼리 합성만 바뀌고 선언 shape는 그대로다.

---

## Step 5 — Panel (`docs/design/...` §2, `035`·`045`·`046`·§17.1.x·§17.9/10)

### 진입조건

Step 3(쓰기 측 메모리) · Step 4(측정 기준선) 완료.

### 무엇

설계 문서 §2가 계약이다. 세 조각:

1. **`grain`을 선언한다** — `instrument_instant` / `instant` / `rows`. **선언하지 않은 등록은
   거절한다.**
2. **`PanelLookback`(`CalendarLookback` · `RowsLookback`)과 `SeriesLookback`(`InstantsLookback`)**.
   타입이 steering을 한다 — `rows` grain은 `PanelLookback`을 받지 않고, panel grain은
   `SeriesLookback`을 받지 않는다.
3. **`Panel`이 물질화된 2d 표가 된다** — 불변, columnar, in-process cache. spill은 §7-2에 따라
   Step 7과 함께 판단한다(공유할 상대가 그때 생긴다).

### 분리 불가 조건 — 이 단계의 가장 중요한 한 줄

**`grain` 거절과 `RowsLookback`의 의미 변경은 같은 릴리스에 같이 들어가야 하고 따로 나갈 수
없다.** 설계 §2.4·§7-3의 논거: 오늘 `RowsLookback(313)`이라고 쓰인 모든 등록이 내일 다른 뜻이
되는데, **균형 잡힌 패널에서는 두 뜻의 결과가 같아서 테스트로도 안 잡힌다.** 모든 기존 등록이
한 번은 손으로 편집되게 만드는 것(= `grain` 거절)이 그 침묵을 막는 유일한 장치다.

### 인수조건

- `grain` 없는 등록이 **세 값을 이름으로 대며** 거절하고, 거절 메시지가 `RowsLookback`의 새 뜻을
  같이 말한다.
- `grain: rows` dataset 위의 `RowsLookback`이 **타입 오류**로 거절하며 `InstantsLookback`을 이름으로 댄다.
- `035`가 같이 닫힌다 — panel이 columnar이므로 별도 accessor를 만들지 않고 panel을 노출한다.
- **byte-identical 회귀**: 캠페인 레인 C의 인수조건과 같은 형태로, 같은 모델이 panel 등록과 legacy
  등록에서 **양방향 full anti-join 0행**. **타이밍을 읽기 전에** 확인한다.
- workspace 문서 마이그레이션은 **write-forward, 이전 shape 한 릴리스 decode 가능, move가 아니라 copy.**
- `test_all` green.

### 되돌리기

상. workspace 문서가 움직인다. 캠페인 §6의 *"열리지 않는 workspace"* 위험이 그대로 적용된다.

---

## Step 6 — `040`: agenda는 공유 가능하다

소유자 결정 2026-08-31, 미구현. 실환경에서 확인됐다 — 같은 cadence의 factor 6개가
`rebalance-mkt`, `rebalance-smb`, … 여섯 개의 **완전히 동일한** agenda 선언을 강요당했다.

**무엇:** `strategy_configs`를 `agenda_id`가 아니라 component id로 다시 키잉한다. workspace 문서
마이그레이션이 붙는다.

**인수조건:** 두 strategy component가 같은 `agenda_id`를 가리키고 둘 다 등록된다. 오늘의
`workspace.strategy_config.register.conflict` 거절이 **agenda가 아니라 붙잡고 있는 strategy를**
이름으로 대는 것은 040이 미구현이어도 별개로 유효하다.

**되돌리기:** 하 — 다만 문서 shape가 바뀌므로 Step 2의 트랜잭션이 먼저 들어와 있어야 한다.

---

## Step 7 — Run: 설정과 기록을 가른다 (`docs/design/...` §4, `034`·`023p`·§17.3~17.6)

### 진입조건

Step 2(트랜잭션) · Step 6(`040`) 완료. **가장 마지막인 이유는 되돌리기가 가장 비싸기 때문이다.**

### 무엇

설계 §4가 계약이다.

- **Run이 등록되는 재사용 객체**가 된다 — universe · period · venue · execution input · initial
  account · agenda를 들고, 전략 여럿을 담는다. 각 전략은 **자기 Account**를 가진다(§7-4).
- **기록이 둘로 갈린다** — `run.json`(설정)과 `strategies/<id>@<fp8>/`(output). 디렉터리 이름이
  §17.4의 *"이게 몇 번 tweak한 전략인가"*를 답한다.
- `run.json`이 **execution input id를 든다** → `034` 닫힘.
- **verb가 생긴다** — `vqapr rm run` / `vqapr rm strategy`. 안전하게 지우는 기계
  (`RunRecordWriter._clear` + heartbeat + lock)는 이미 있고 부르는 것만 없다.
- `list runs` / `list strategies`가 record의 새 필드로 filter한다. **새 I/O를 만들지 않는다** —
  `cli/list_.py`가 이미 record 전체를 읽고 네 필드만 쓰고 버린다.
- **실환경 A7(등록이 바이트를 안 지킨다)을 여기서 같이 닫는 것이 자연스럽다** — run record는 이미
  `source_digest`를 들고 dataset 등록만 안 든다.

### 인수조건

- 한 run에 전략 셋을 넣고 `--jobs 3`으로 돌려 **전략별 NAV 셋**이 나온다.
- `record.json`이 답하지 못하던 질문에 답한다 — 어떤 `.py`가 돌았나, 그 전략 자신의 fingerprint는
  무엇인가, 어떤 execution convention이었나, 어떤 instrument 위였나.
- `ou-ff5@*` 디렉터리를 세는 것이 tweak 횟수다.
- `vqapr rm`이 살아 있는 run을 보호하고(heartbeat), 죽은 run의 잔해만 지운다.
- **인덱스 파일은 만들지 않는다** — `docs/design/run-record-layout.md`의 논거는 그대로 유효하다.
- `test_all` green + showcase 전부 green.

### 되돌리기

최상. run 기록 레이아웃과 workspace 문서가 같이 움직인다. **ExecPlan 필수.**

---

## 이 캠페인에 넣지 않은 것, 그리고 이유

- **`workspace.py` 분해(구조 Step 4.1)와 `SimulationFlow` 분해(구조 Step 5).** 둘 다 진단이 여전히
  옳다 — `workspace.py` 1,548줄이 8개 선언 map을 15곳에서 위치 인자로 흘리고, `SimulationFlow`는
  ~1,750줄 / ~50 메서드에 `_execute_due` 하나가 284줄이다. **그런데 Step 2·5·7이 `workspace.py`를,
  Step 3·5가 `flow/`를 어차피 다시 쓴다.** 먼저 쪼개면 같은 코드를 두 번 옮긴다. 크기는 진단
  문서 §1처럼 계속 재되 **관측값으로만** 읽는다(record `118`의 결정).
- **척추.** `optimize`, `plan_orders`, `Account.prepare_fill`, `Fill.__post_init__`, `ModelWindow`의
  requirement 검사, 네 개의 시계, frozen input, warm-up과 atomic callback acceptance.
- **PIT 규칙.** field는 표현식이지 statement가 아니다 — **look-ahead가 문법으로 막힌다는 성질**을
  어느 단계도 건드리지 않는다.
- **field당 자유 SQL.** 여는 순간 위 성질을 잃는다. 막히는 사례가 나오면 `049`에 기록하고, 그때
  ruling 변경으로 다룬다.
- **docstring 축약.** 이 저장소의 docstring은 결정의 근거 기록이다. 코드를 옮길 때 근거도 옮긴다.
- **닫힌 이슈 파일 이동.** `src/` 103곳과 `docs/` 154곳이 번호를 인용한다. 색인은
  `docs/issues/README.md`가 진다.

---

## 게이트

| 게이트 | 명령 | 언제 |
|---|---|---|
| lint | `uv run ruff check src/` | 모든 단계 |
| fast | `PYTHONUTF8=1 uv run pytest tests/ -q -rs` | 모든 단계. **고정 하한을 쓰지 말고 분기한 커밋에서 직접 재서 비교하라.** `-rs` 필수 — skip은 돌지 않은 테스트다 |
| full incl. slow | `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` | Step 1 · 3 · 5 · 7 |
| surface | 다섯 쌍 identity · scaffold 셋이 같은 import · `_internal/`에 bridge 0 | Step 1 |
| transaction | 거절된 문서 등록 후 workspace가 byte-identical | Step 2 |
| cost | `049`의 anti-join을 **타이밍보다 먼저** | Step 4 · 5 |
| showcase | 9개 전부 완주 | Step 1 · 5 · 7 |

> **하한을 숫자로 박지 마라.** 선행 캠페인 §4가 그 실수를 자기 인수조건에서 냈다 — 1497을 하한으로
> 적었더니 레인 A가 1515로 올린 뒤 다른 레인이 **1512 passed + 5 skipped**를 green으로 판정했다.
> 통과가 3개 줄었는데 하한이 낡아서 가려졌다.

---

## 위험

| 위험 | 가장 이른 신호 | 대응 |
|---|---|---|
| **Step 1을 쪼개고 싶어진다.** 여덟 접촉면이 한 커밋에 들어가는 것이 불편해 보인다 | "scaffold만 먼저" 또는 "loader만 먼저"라는 문장이 나온다 | **gjc가 그것을 두 번 시도해 두 번 revert했다**(`gjc-handoff/README.md` §7.1·§7.2). ExecPlan에 그 인용을 박아 둔다 |
| **green tree, 옮겨진 지표, 틀린 숫자.** 이 repo에 세 번 기록돼 있다(`docs/issues/archive/041`, `cli/run.py:170`, record `115` erratum) | 인수조건 tolerance가 느슨해지거나 numeric baseline이 재생성된다 | 어떤 단계도 `settle_contract_hml.fixture.json`이나 showcase baseline을 재생성하지 않는다. 필요해 보이면 멈추고 escalate |
| **`RowsLookback`이 조용히 뜻을 바꾼다** — 균형 잡힌 패널에서는 두 뜻의 결과가 같다 | Step 5에서 `grain` 거절 없이 이름만 바뀐다 | 설계 §7-3. **분리 불가.** 같은 릴리스에 같이 넣는다 |
| **열리지 않는 workspace** — Step 5/7이 문서를 마이그레이션한 뒤 revert하면 모든 명령이 실패한다 | 마이그레이션이 copy가 아니라 move | write-forward, 이전 shape 한 릴리스 decode 가능, copy |
| **Step 3의 포맷 변경이 기존 run 기록을 못 읽게 만든다** | 이전 shape 읽기 경로 없이 병합 | 두 shape를 한 릴리스 동안 읽는다. `analysis/performance.py`가 그 증인이다 |
| **testbed가 이미 고친 것을 다시 보고한다** | `vqapr-final-testbed/KNOWN-ISSUES.md`가 wheel보다 낡음 | **각 단계 병합 후 wheel을 다시 빌드하고 `KNOWN-ISSUES.md`를 `docs/issues/`에서 재생성한다.** 오늘 이미 넷(`030`·`032`·`038`·`043`)이 낡았다 |
| **계획이 틀린 facade를 향한다** — 2026-08-24~28에 나흘 동안 실제로 일어났다 | 없다. 코드 읽기로는 안 보였다 | Step 1 착수 전에 **실제 CLI journey 위의 tracer를 한 번 더 돌린다.** 그것이 유일하게 그 오류를 잡은 방법이다 |
| **완료된 절반과 차단된 절반이 한 단위에 묶인다** | 어떤 단계가 "절반은 됐는데 나머지가 막혔다"로 보고된다 | `G010`이 그래서 아직 `active`다. **쪼개서 하나는 닫고 하나는 blocked로 세운다** — 섞인 것은 닫히지도 멈추지도 않는다 |

---

## 진척 지표

각 단계 후 재측정해 implementation record에 적는다. **관측값이지 임계값이 아니다.**

```bash
# 저자 표면이 하나인가 (목표 0)
uv run python -c "
import vqapr.public as p, vqapr.authoring as a
print(sum(getattr(p,n) is not getattr(a,n) for n in
  ('DataModel','StrategyModel','Constraint','ConstraintBounds','ConstraintFinding')))"

# bridge 총량 (목표 0)
wc -l src/vqapr/_internal/strategy_bridge.py src/vqapr/_internal/models/agent_first.py

# scaffold가 지명하는 표면의 수 (목표 1)
grep -o "from vqapr[a-z_. ]*import" src/vqapr/extension/scaffold.py | sort -u

# god module — 관측값으로만 (record 118)
find src/vqapr -name '*.py' -exec wc -l {} + | sort -rn | head -5

# 게이트
uv run ruff check src/ && PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rs
```
