# 삭제 캠페인 — 다시 만든 바퀴를 지우고, 두 flow를 하나로

| | |
|---|---|
| **작성 시각** | 2026-09-03 KST (+09:00) |
| **기준 커밋** | `develop @ 1dadb1e8` (= `v0.3.0` + walkthrough 1 commit). 이 문서의 모든 경로와 수치는 그 커밋에서 직접 잰 것이다. 착수는 `50941347`(record `140`) 위에서 |
| **트리 상태** | `v0.3.0` 태그 기준 fast **1314** / slow **13** · ruff clean · showcase 9/9 |
| **선행 캠페인** | `docs/refactoring/2026-09-02-the-convergence-campaign.md` — Step 0–7 완료, records `129`–`139` |
| **진단** | `docs/diagnostics/README.md` §0 (2026-09-02)과 이 문서 §0의 재검토. 이 문서는 새 진단을 하지 않는다 |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` (§17) → `docs/design/the-panel-the-surface-and-the-run.md` |
| **소유자 결정 (2026-09-03)** | 아래 §0의 넷. 전부 이 세션에서 소유자가 직접 내렸다 |

> **이 캠페인이 더하는 것은 순서·단위·인수조건뿐이다.** 여덟 단계 전부가 이미 열린 이슈이거나
> (`052`·`053`·`054`), 선행 record가 "하지 않은 것"으로 남긴 자리이거나 (`137`·`139`), 소유자가
> 이 세션에서 내린 결정이다. 무엇이 왜 문제인지는 이슈 파일과 진단 문서에 있다.

---

## 0. 소유자 결정 넷, 그리고 왜 이 순서인가

### 결정

| # | 결정 | 근거 |
|---|---|---|
| D1 | **DataModel은 account 없고 execution 없는 StrategyModel처럼 돈다.** 둘은 하나의 flow를 공유한다 | architecture §17.2 (*"base는 하나"*). 오늘 `flow/materialize.py:1208`은 agenda도 `SimulationFlow`도 거치지 않는 자기 루프를 돈다 |
| D2 | **정보를 담지 않는 등록 섹션은 지운다.** `valuation_configs`·`monitoring_policies` | *"key는 사용할 때 만들어야 해. 미리 만들어두면 안돼."* 두 섹션은 agenda가 이미 가진 `role`을 되풀이할 뿐이다 (§Step 3) |
| D3 | **바퀴를 다시 만들지 않는다.** dict↔객체 검증/직렬화는 pydantic, 타입이 실린 기록은 parquet | `workspace_codec.py` 1,168줄 + `declarations.py` 1,150줄이 손으로 쓴 스키마 검증이다. `flow/run_records.py`의 `.types.json` 사이드카는 parquet이 하는 일이다 (§Step 4·5) |
| D4 | **순서**: 053 → 054 → B(D2) → C-1(D3 pydantic) → parquet → C-2 → A(D1) | 아래 |

### 순서의 제약

```
Step 0  showcase gate + dead code       <- 뒤의 모든 단계를 지킨다. 반나절
   |
Step 1  053  InstantsLookback           <- correctness. 독립
   |
Step 2  054  Observation 신뢰 생성       <- 372s 중 250s. 독립
   |
Step 3  B    두 섹션 퇴역               <- Step 4가 옮길 kind를 9 -> 7로 줄인다
   |
Step 4  C-1  pydantic이 codec을 대체     <- 가장 비싸고 되돌리기 어렵다. ExecPlan
   |
Step 5  기록 parquet                    <- Step 4와 독립이지만 같은 "바퀴" 결정. Step 6 전에
   |
Step 6  C-2  SimulationFlow 4분할        <- Step 5가 기록 쓰는 쪽을 먼저 바꾼 뒤에
   |
Step 7  A    DataModel = flow 하나       <- Step 6의 절단선이 곧 A의 경계. ExecPlan
```

- **Step 3이 Step 4 앞인 이유.** Step 4는 kind마다 pydantic 모델 하나를 만든다. 없앨 kind를 먼저
  없애야 모델을 만들지 않는다.
- **Step 5가 Step 6 앞인 이유.** Step 6은 `simulation.py`를 네 파일로 자르고, 그중 하나가 기록에
  쓰는 쪽이다. 기록 포맷을 먼저 바꿔야 그 파일을 한 번만 옮긴다.
- **Step 6이 Step 7 앞인 이유.** D1의 실현은 "3·4행이 빠진 Flow"다 (§Step 6의 표). 절단선이 먼저
  있어야 그 위에서 DataModel flow를 정의한다.

### 동시 진행 중인 것 — 이 캠페인이 손대지 않는다

이 문서를 쓰는 동안 다른 세션이 monitoring finding을 `vqapr.monitoring` 표로 기록에 남기는 작업을
하고 있었고, **record `140`으로 `develop @ 50941347`에 들어왔다** (2026-09-03). 이 캠페인의 record
번호는 `141`부터다.

- Step 6(simulation.py 분할)의 진입조건 "record `140` 병합"은 **충족됐다.** `140`이 더한
  `_record_findings`는 Step 6의 valuation/monitoring 파일로 간다.
- Step 5(parquet)는 `140`이 더한 `vqapr.monitoring` 표를 다른 표와 같이 다룬다 — 표가 하나 늘 뿐이고
  포맷 변경과 직교한다.

**각 단계는 `develop`이 green인 상태로 들어간다.** 단계 하나 = 브랜치 하나 = implementation record
하나 = `--no-ff` 병합 하나. ExecPlan은 Step 4·7에 만든다 (Step 6은 Step 5 완료 시점에 다시 재서
결정). 나머지는 bounded inspect-edit-validate다.

---

## Step 0 — 게이트와 죽은 코드 (`052` 후반, vulture 2건)

### 왜 여기인가

`052`의 남은 절반: showcase 9개가 지금 돌지만 **`pytest`가 하나도 수집하지 않는다.** 이 캠페인의
Step 3·4·5·7이 전부 계약을 바꾸므로, 게이트 없이 가면 `052`가 발견한 방식으로 다시 썩는다.

### 오늘의 사실

- 각 `showcases/show_00N_*/run.py`가 `main()`을 갖고 `if __name__ == "__main__": main()`으로 끝난다.
  자기 디렉터리를 `sys.path`에 넣으므로 repo root에서 실행된다.
- **`show_003`만 gitignore된 `data/DW`에 의존한다** (`run.py:5`, `.gitignore:17`). 나머지 여덟은
  자기 fixture를 만든다.
- vulture: `workspace_codec.py:1118 _encode_requirement`, `:1139 _decode_requirement` — src 어디서도
  호출되지 않는다 (`grep` 0건, `__pycache__` 제외).

### 무엇

1. `tests/showcases/test_every_showcase_completes.py` — `slow` 표시, 여덟 showcase를 각각
   subprocess로 `main()`까지 돌리고 exit 0을 단언한다. **`show_003`은 제외하고 그 이유를 테스트
   docstring에 적는다** (`data/DW`는 repo 밖이고, 조건부 skip은 이 저장소에서 "돌지 않은 테스트"다
   — 선행 캠페인 §게이트). show_003은 release 전 손으로 돈다는 사실을 `.agent/project.yaml`의
   `test_all` 주석에 적는다.
2. `_encode_requirement` / `_decode_requirement` 삭제.

### 인수조건

- `uv run pytest tests/ -q -m slow -rs`에 여덟 showcase가 들어 있고 전부 passed, skip 0.
- `uv run vulture`가 `src/`에 대해 0건 (tests의 `_decision` 1건은 이 단계 밖).
- implementation record 없음 — harness-only (AGENTS.md "Implementation records"). `052`를 CLOSED로.

### 되돌리기

자명.

---

## Step 1 — `053`: `InstantsLookback`이 행이 아니라 instant를 센다

### 오늘의 사실

`data/scan.py:1266-1269`의 ranking이 `count(<field>) OVER (PARTITION BY instrument ORDER BY
<available_at, key fields> DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`다. 한 instant에
행이 셋인 `grain: rows` 표에서 `InstantsLookback(2)`는 최신 instant의 행 둘을 준다. docstring
(`data/lookback.py:44`)과 거절 문구(`data/datasets.py:298`)는 둘 다 "instant"라고 말한다.

같은 모양이 **proof에도** 있다: `_prove_rows_bound`(`scan.py:1027`)와 읽기 안의 next-callback proof
(`:1281-1290`)가 `count(<field>)`로 **행**을 세어 "이 이름은 n개를 갖는다"를 증명한다. rank만 고치고
proof를 두면 proof가 참인데 창이 짧아지는 이름이 생긴다.

### 무엇

- rank: 필드별 non-null을 유지하되 **instant 단위**로 센다 — `dense_rank() OVER (PARTITION BY
  instrument ORDER BY available_at DESC)`를 non-null 행에만 매기는 형태. 구현 세부는 record에.
- proof 둘: `count(DISTINCT available_at)` (필드가 non-null인 행의 instant 수)로 맞춘다.
- `grain: rows`에서의 `CalendarLookback` 허용 여부는 **이 단계가 정하지 않는다.** `053`이 기록한
  두 번째 발견으로 남기고, 필요해지는 소비자가 나오면 ruling으로 다룬다.

### 인수조건

- `053`의 재현: instant 4 × 행 3인 표에 `InstantsLookback(2)` → **instant 2, 행 6**. 테스트가 그것을
  직접 단언한다 (`tests/data/test_lookbacks_follow_grain.py`에 추가).
- panel grain에서는 행 = instant이므로 `tests/data/test_lookbacks_follow_grain.py`의 기존 케이스
  전부 그대로 green.
- `experiments/exp_049_the_measurement/`의 `rows` 쪽이 `InstantsLookback(2000)` 대신 instant 수로
  선언할 수 있게 된다 — 그 실험을 다시 돌려 anti-join 0을 확인한다 (타이밍은 이 단계의 게이트가
  아니다).
- `053` CLOSED, record 하나.

### 되돌리기

하. SQL 두 곳.

---

## Step 2 — `054`: 프레임워크가 만든 행은 검증하지 않는다

### 오늘의 사실

`models/calls.py:78`이 `rows(alias)`의 모든 행마다 `Observation(...)`을 만들고,
`authoring.py:204`의 `__post_init__`이 `_identifier`·`_tz_aware`·`_copy_values`를 돈다.
`_copy_values`는 값마다 키의 문자를 순회한다 (`:160`). 프로파일: 읽기 9.85s 중 6.81s가 여기,
그중 `isspace` 14.6M회 2.79s, pytz `fromutc` 0.86s (`054`). 이름은 등록 때 검증됐고 (`035` ruling),
`available_at`은 scan의 `TIMESTAMPTZ` 컬럼이 보장한다.

`Observation(`을 만드는 자리는 src에 **`calls.py:78` 하나뿐이다.**

### 무엇

- `Observation`에 검증을 건너뛰는 생성 경로 하나 (`object.__new__` + `__setattr__`, 또는
  classmethod `_trusted`). `__post_init__`은 저자가 손으로 만드는 경우를 위해 그대로 둔다 — `054`
  "What not to do".
- `calls.observations`가 필드 이름 튜플을 **한 번** 검증하고 그 경로로 만든다.
- pytz: duckdb가 돌려주는 tz-aware datetime의 zone 변환이 행마다 든다. scan 쪽에서 한 번에 처리할
  수 있는지 (`TIMESTAMPTZ` → epoch 또는 arrow 경유) 이 단계에서 **재고** 기록한다. 0.86s는 핵심이
  아니므로 답이 없으면 남긴다.

### 인수조건

- `054`의 프로파일을 같은 입력으로 다시 잰다: `rows(alias)`에서 `Observation` 생성이 scan보다
  **작다** (오늘 70/30 → 목표는 숫자로 박지 않는다, 분기한 커밋에서 재서 비교).
- `experiments/exp_049_the_measurement/`의 `rows` 쪽 wall이 줄고 anti-join 0. **anti-join을 타이밍보다
  먼저** (선행 캠페인 §게이트 "cost").
- 저자가 만든 `Observation(values={"a b": 1})`은 여전히 거절된다 — 테스트.
- `054` CLOSED, record 하나.

### 되돌리기

하.

---

## Step 3 — B: `valuation_configs`·`monitoring_policies` 퇴역

### 오늘의 사실

같은 사실이 세 번 적힌다:

```yaml
agendas:
  daily-valuation: {role: valuation, ...}        # (1) agenda 자신의 role
valuation_configs:
  daily-valuation: {agenda_id: daily-valuation}  # (2) 키는 버려진다 (declarations.py:74-78)
runs:
  my-run: {valuation: {agenda_id: daily-valuation}}  # (3) run이 고른 agenda
```

- (2)는 `ValuationConfig(agenda_id, role=VALUATION)`로 decode된다 (`workspace_codec.py:847-871`).
  role은 (1)이 이미 갖고 있고, run 등록은 (3)을 받을 때 `workspace.py:1037 _require_agenda`로 (1)의
  role을 직접 본다. **(2)가 더하는 정보는 없다.** `monitoring_policies`는 구조가 동일하다
  (`:872-889`).
- **사용자가 실제로 겪는 결함:** run 등록은 (2) 없이 통과하는데 `vqapr run`은
  `flow/preflight.py:578 workspace.valuation_config(...)`에서 (2)를 찾다가 거절한다. 등록은 받고
  실행은 거절하며, 고치라는 것이 이미 두 번 적은 사실이다.
- 접촉면: `workspace.py`(`_State` 필드 둘, `register_*`·`_merge_*`·`valuation_config()`·
  `monitoring_policy()`·remove blocker), `workspace_codec.py`(detach·encode·decode),
  `declarations.py:74-89`, `flow/preflight.py:578-585`, `cli/list_.py:54-55`, `cli/new.py:23,196-202`,
  `SKILL.md:65`, 테스트 11 파일.
- `strategy_configs`는 **남는다.** 전략↔agenda binding이라는 정보를 담고 있다 (records `138`·`139`).

### 무엇

- 두 섹션, 두 registry kind, 두 dataclass의 **registry 역할**을 지운다. `ValuationConfig`·
  `MonitoringPolicy` 타입 자체는 `RunDefinition.valuation`/`.monitoring`의 값으로 남는다 — run이
  agenda를 고른다는 사실의 타입이고, (3)이 그것을 만든다.
- preflight는 run 문서의 (3)을 그대로 쓰고 (1)의 role만 확인한다. drift check는 사라진다 — 비교할
  두 번째 사본이 없어졌으므로.
- `new agendas` 템플릿과 `SKILL.md` 7번 항목에서 두 섹션을 뺀다.
- **기존 문서:** 사용자 선언 문서는 지금처럼 `declarations.py:878` "unrecognized section"으로
  거절한다 — 무엇을 지우라는지 이름을 댄다. `.vqapr/workspace.yaml`은 **읽을 때 두 섹션을 버리고**
  다음 쓰기에서 빠진다. 정보가 0인 섹션이라 조용히 뜻이 바뀌는 경로가 아니다 (설계 §2.4의 금지는
  "한 뜻을 두 철자로"이고 이것은 그 경우가 아니다).

### 사용자에게 바뀌는 것

| | 전 | 후 |
|---|---|---|
| 선언 YAML | 섹션 셋 | `agendas:` + `runs:`의 `valuation:` |
| `vqapr run` | valuation config 없으면 preflight 거절 | agenda가 role `valuation`이면 통과 |
| `list valuation-configs` | 있음 | 없음 |
| 0.3.0 workspace | — | 열린다. 두 섹션은 다음 쓰기에서 사라진다 |

### 인수조건

- `_State`가 7 필드, codec의 root 집합에서 둘이 빠짐, `grep -rn valuation_configs src/` 0건.
- 두 섹션이 든 0.3.0 `workspace.yaml`을 `Workspace.open`이 연다 (fixture 테스트).
- 두 섹션이 든 **선언 문서**는 섹션 이름을 대며 거절된다.
- valuation config 없이 등록한 run이 `vqapr run`을 완주한다 — 오늘 거절되는 그 경로의 테스트.
- fast+slow 전부, showcase 게이트 green. record 하나.

### 되돌리기

하. 문서 shape 축소이고 남는 정보가 없다.

---

## Step 4 — C-1: pydantic이 손으로 쓴 codec을 대체한다 (ExecPlan)

**ExecPlan:** `.agent/plans/active/step-04-pydantic-replaces-the-codec.md`. 여기는 요약이다.

### 오늘의 사실

| 손으로 쓴 것 | 어디 | 바퀴 |
|---|---|---|
| "정확히 이 키들" 검사 kind 9종 | `workspace_codec.py:417-939 _decode` 520줄 | `extra="forbid"` + 필수 필드 |
| `isinstance` 검사 | codec 70 · declarations 12 · workspace 22 · `flow/run.py` 40 | 필드 타입 |
| str → `datetime`/`Decimal`/`Enum` | codec 곳곳 | 필드 타입 |
| 빠진 키를 한 번에 알리는 `_require_keys` | `declarations.py:178` | `ValidationError.errors()`가 원래 그렇다 |
| 객체 → dict `_encode` | `workspace_codec.py:292-398` | `model_dump(mode="json")` |
| 불변 복사 `_detach_*` 8종 | `workspace_codec.py:150-252` | frozen model은 복사가 필요 없다 |

pydantic은 record `129`가 뺐다 — "선언만 있고 import 0". 그것은 옳았고, 이 단계는 **실제로 쓰는**
다른 결정이다 (D3).

### 무엇

- kind 7종(`SourceSpec`·`DatasetRegistration`·`ExecutionInputRegistration`·`ComponentRef`·
  `OperationAgenda`·`StrategyConfig`·`RunDefinition`)과 그 값 타입이 **frozen pydantic 모델**이
  된다. `.of()`는 필드 대입 이상을 하는 경우(예: `DatasetRegistration.of`의 grain 정합성)만
  `model_validator`로 남는다. `with_span`/`with_schema`(10곳)는 `model_copy(update=)`.
- `workspace.yaml` ↔ `_State`: `yaml.safe_load` → `model_validate` / `model_dump` → `yaml.safe_dump`.
  `_decode`·`_encode`·`_detach_*`는 삭제.
- 선언 문서 → 객체: 같은 모델의 `model_validate`. `declarations.py`에 남는 것은 pydantic이 모르는
  일뿐 — 상대 경로를 선언 파일 기준으로 풀기, `.py`를 ast로 읽어 유일 subclass 찾기, 참조 검사,
  그리고 **`ValidationError` → `Failure` adapter 하나** (`loc` → `source=_at(key_path)`,
  `type` → `code`, `_nearest_hint`는 unknown-key 오류에 붙인다).
- `Workspace`는 generic만 남는다: 잠금·읽기·쓰기·`Transaction`, `_merge_declaration`,
  `_config_lookup`, 참조 검사(`_require_run_references`·`_references_in`).

### 인수조건

- `grep -c isinstance` 가 codec·declarations·`flow/run.py`에서 오늘의 122 → 측정값으로 기록 (하한
  없음). `workspace_codec.py`는 파일로서 사라지거나 모델 정의만 남는다.
- **거절 품질 유지:** 선언 오류에 걸린 테스트 23 파일이 green. 문구가 바뀌면 테스트를 옮기되
  `fix`·`explain`·`source` 세 필드는 모든 거절에 남는다 — `tests/cli/test_agent_surface.py`가
  그것을 본다.
- 0.3.0 `workspace.yaml` fixture가 그대로 열리고, 다시 쓰면 **byte-identical**이거나 차이가 키
  순서뿐이다 (테스트가 diff를 찍는다).
- fast+slow, showcase 게이트, `uv build`. record 하나. `pydantic>=2,<3` 의존성 추가는 record에
  버전과 함께.

### 되돌리기

중. 브랜치 하나에서 하고 병합 전까지 develop은 손대지 않는다. 문서 shape는 바뀌지 않으므로
revert가 데이터를 깨지 않는다.

---

## Step 5 — 기록을 parquet으로

### 오늘의 사실

`flow/run_records.py`가 표마다 `<table>.jsonl` + `<table>.jsonl.types.json`을 쓴다. Decimal과
tz-aware datetime을 JSON으로 왕복시키려고 `_type_name`·`_learn_types`·`_encode`·`_decode`
(`:220-290`)가 타입을 따로 적고 되돌린다. 읽기는 `read_table`이 `json.loads`를 행마다 (`:1039-1052`).
진단 §3.3이 *"parquet으로 내면 tz가 스키마에 실려 함정이 사라진다"*고 적었고 record `135`는 JSONL을
택했다. pyarrow는 이미 의존성이다.

### 무엇

- 표 하나 = `<table>.parquet`. `RunRecordWriter.append`는 `pyarrow.parquet.ParquetWriter`로 row
  group을 흘려 쓴다 (스트리밍 성질 `135` 유지). Decimal → `decimal128`, datetime → `timestamp[us, tz]`.
- `.types.json` 사이드카와 `_learn_types`·`_encode`·`_decode` 삭제. `read_table`/`read_typed_table`은
  `pq.read_table(...).to_pylist()` 위의 얇은 함수 — `show run --table … --limit`의 필터는 duckdb로
  parquet을 직접 읽는다.
- `record.json`·`run.json`·`strategy.json`은 JSON으로 남는다 (작고, 표가 아니다).
- 진행 중 record `140`의 `vqapr.monitoring` 표는 다른 표와 같이 간다.

### 인수조건

- `tests/flow/test_the_record_reads_back_typed.py`: Decimal이 Decimal로, tz-aware가 같은 tz로 돌아온다
  — `.types.json` 없이.
- 기록을 `duckdb.read_parquet`으로 읽어 등록하면 **9시간 밀리지 않는다** (A5의 재현이 테스트로).
- `tests/qa/test_run_records_survive_and_race.py`: 죽은 run이 row group까지 남긴다.
- 0.3.0 JSONL 기록은 **읽지 않는다** (breaking, 캠페인 정책). `read_record`가 `.jsonl`을 보면 이름을
  대며 거절한다.
- fast+slow, showcase. record 하나.

### 되돌리기

중. 기록 레이아웃 변경.

---

## Step 6 — C-2: `SimulationFlow`를 네 단계로

### 진입조건

record `140`(monitoring findings) 병합 — **충족, `50941347`**. Step 5 완료. **착수 시점에 다시 잰다** — 아래 표는
2026-09-03 `1dadb1e8` 기준이고 `140`이 메서드를 더한다.

### 오늘의 사실

`flow/simulation.py` 2,147줄, `SimulationFlow` 메서드 54개, `_execute_due` 284줄(`_due_boundary` 14연쇄).
메서드 이름이 이미 네 단계로 갈린다:

| 단계 | 메서드 | 줄 | 가는 곳 |
|---|---|---|---|
| 루프와 실패 봉투 | `run` `_guard` `_failure` `_due_boundary` `_pending_due` `_dispatch_due` | ~300 | `flow/simulation.py`에 남는다 |
| callback (decide → intent) | `_dispatch_callback` + `_callback_*` 9 + `_stamp_intent` `_validate_intent_authority` `_accept_intent` `_accept_valuation` `_record_defaults` + state restore/candidate 4 + `_load_visible_strategy_state` | ~700 | `flow/callback.py` |
| execution (intent → fill → commit) | `_execute_due` `_publish_account_commit` `_execution_horizon` `_bound_rules` `_bind_registry_to_venue` | ~400 | `flow/execution.py` |
| valuation / monitoring (mark → account) | `_value_due` `_dispatch_valuation` `_standalone_*` 3 `_commit_standalone_valuation` `_committed_marks` `_valuation_instant` `_dispatch_monitoring` `_publish_marked` + `140`의 `_record_findings` | ~450 | `flow/valuation.py` |

### 무엇

- 단계마다 모듈 하나. 각 모듈은 `SimulationFlow`의 필드 중 자기가 쓰는 것만 받는 작은 클래스 또는
  함수 집합. `SimulationFlow`는 루프와 위임만 갖는다.
- **척추는 호출 위치만 옮긴다.** `plan_orders`·`Account.prepare_fill`·`optimize`·`Fill.__post_init__`
  내용 불변.
- 절단선은 **Step 7이 요구하는 것**이다: DataModel flow = 1행 + 2행의 절반 (상태 복원·창 읽기·
  model 호출·evidence·commit) + 출력 단계. 3·4행이 없다.

### 인수조건

- 사용자에게 바뀌는 것 0: fast+slow 전부, showcase 게이트, 그리고 **record `104`의 tracer**로
  CLI journey 하나가 같은 함수들을 같은 순서로 지난다.
- `simulation.py`의 크기와 메서드 수를 record에 측정값으로 (하한 없음).

### 되돌리기

중. 순수 이동.

---

## Step 7 — A: DataModel은 account와 execution이 없는 flow다 (ExecPlan)

**ExecPlan:** Step 6 완료 시점에 만든다. 여기는 계약이다.

### 오늘의 사실

| | 전략 실행 | DataModel materialization |
|---|---|---|
| 호출 | `vqapr run <run-id>` (등록) | `vqapr run <spec.yaml>` (`datamodel:` 파일, `cli/run.py:8`) |
| 루프 | agenda → `SimulationFlow` | `materialize.py:1208 for evaluation_time in times` |
| 기록 | `run.json` + `strategies/<id>@<fp8>/` | `record.json` (record `139` "하지 않은 것") |
| 조회·삭제 | `list runs` `show strategy` `rm run` | 별도 |

`authoring.py:252`의 `Model` base는 이미 하나다 (record `132`). **표면은 하나인데 flow가 둘이다.**

### 무엇

- `runs:`에 DataModel도 들어간다. run이 `datamodels:` 항목을 가지면 각각이 자기 agenda(
  registered binding, `138`과 같은 모양)로 돌고, 결과가 등록된 dataset이 된다. 전략과 같은 run에
  있을 수 있고 — 그 run의 전략이 그 dataset을 읽을 수 있는지는 **ExecPlan에서 결정** (같은 run 안
  순서 의존 vs 별도 run).
- `MaterializationSpec`·`RunRecordSpec`·자체 루프·`record.json` 삭제. `_stage_and_publish`와
  lineage는 DataModel flow의 "publication 단계"로 `flow/publication.py`.
- `vqapr run`은 id만 받는다. `check`도.
- 기록: `runs/<run-id>/datamodels/<id>@<fp8>/` — 전략 기록과 같은 축.

### 인수조건 (초안, ExecPlan이 확정)

- `vqapr run <spec.yaml>`이 사라지고 `new datamodel`이 `runs:` 블록을 emit한다.
- showcase `show_002`·`show_003`·`show_007`(materialize를 쓰는 셋)이 등록된 run으로 다시 쓰이고
  같은 출력을 낸다 (anti-join 0).
- `flow/materialize.py`가 사라지거나 publication만 남는다.
- fast+slow, showcase, `uv build`. record 하나.

### 되돌리기

상. 기록 레이아웃과 CLI 표면.

---

## 이 캠페인에 넣지 않은 것, 그리고 이유

- **`_internal/filelock.py`를 `filelock` 패키지로.** 후보다 — OS 락은 프로세스가 죽으면 풀려서
  mtime 기반 stale 판정이 필요 없다. Step 5 뒤에 재서 결정한다. run record의 lease 락은 다른
  동물이므로 대상이 아니다 (`filelock.py:1` docstring).
- **panel spill / `--jobs` 공유.** 소유자 결정 "숫자가 나오면". `experiments/exp_049_the_measurement/`
  로 N번 빌드 vs 1번 빌드 + N map을 재는 것은 쌉니다만 이 캠페인의 단계가 아니다.
- **`023p`.** HELD. gate가 되면 안 된다.
- **`027`.** 소유자가 재개한 항목이고 작다. 이 캠페인과 독립이라 아무 때나 끼워 넣을 수 있다.
  Step 4가 등록 경로를 다시 쓰므로 **그 뒤에** 넣는 것이 한 번만 쓰는 길이다.
- **`data/scan.py` 1,343줄.** Step 1·2가 그 안을 고친다. 그 뒤에 크기를 다시 잰다.
- **척추, PIT 규칙, docstring 축약, 닫힌 이슈 파일 이동.** 선행 캠페인과 같다.
- **hot path의 pydantic.** `Observation`·`Fill`·row 객체는 pydantic으로 가지 않는다. 그 자리의
  답은 검증을 라이브러리로 하는 것이 아니라 하지 않는 것이다 (Step 2, `035`).

---

## 게이트

| 게이트 | 명령 | 언제 |
|---|---|---|
| lint | `uv run ruff check src/` | 모든 단계 |
| fast | `PYTHONUTF8=1 uv run pytest tests/ -q -rs` | 모든 단계. **분기한 커밋에서 직접 재서 비교. `-rs` 필수** |
| full incl. slow | `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` | Step 3·4·5·6·7 |
| showcase | Step 0의 테스트 (여덟) + `show_003` 손으로 | Step 3·4·5·7 |
| cost | `exp_049`의 anti-join을 **타이밍보다 먼저** | Step 1·2 |
| tracer | record `104`의 PEP 669 tracer로 CLI journey 비교 | Step 6 |
| deadcode | `uv run vulture` | Step 0, 그리고 Step 4·7 뒤 |

> **하한을 숫자로 박지 마라.** 선행 캠페인 §게이트의 이유 그대로.

---

## 위험

| 위험 | 가장 이른 신호 | 대응 |
|---|---|---|
| Step 4가 거절 문구를 뭉갠다 — pydantic 기본 메시지가 `fix`·`explain` 없이 envelope에 나간다 | `tests/cli/test_agent_surface.py` red, 또는 `stage: "unhandled"`가 envelope에 보임 | adapter가 **모든** `ValidationError`를 잡는다. `cli/main.py`의 outermost except에 도달하는 pydantic 오류는 버그다 |
| Step 4가 hot path로 번진다 | `flow/run.py` 밖의 dataclass가 BaseModel이 되기 시작 | 대상은 kind 7종과 그 값 타입뿐. ExecPlan의 scope 표 밖은 손대지 않는다 |
| Step 5 뒤 큰 기록의 `show run`이 전체를 메모리에 올린다 | `--limit`이 있어도 느림 | duckdb가 parquet을 필터하며 읽는다. `to_pylist()`는 limit 뒤에만 |
| Step 6이 record `140`과 충돌 | 같은 파일 두 갈래 | 진입조건: `140` 병합 뒤 |
| Step 7에서 같은 run 안의 DataModel → Strategy 의존이 순서 문제를 만든다 | `--jobs`가 dataset을 아직 못 읽음 | ExecPlan의 첫 결정. 보수적 기본: 같은 run 안 DataModel은 전략보다 **먼저** 전부 완료, jobs는 전략에만 |
