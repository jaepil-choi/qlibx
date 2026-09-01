# 읽기 경로 캠페인 — 레인, 인수조건, 병합 순서

| | |
|---|---|
| **작성 시각** | 2026-09-01 KST (+09:00) |
| **기준 커밋** | `develop @ 4dd85975`. 이 문서의 모든 행 번호는 그 커밋 기준이다 |
| **트리 상태** | `PYTHONUTF8=1 uv run pytest tests/ -q` → **1497 passed, 14 deselected** · `uv run ruff check src/` → clean |
| **앵커 이슈** | `docs/issues/049` — **오너 ruling이 거기 있고, 이 문서는 그것을 재론하지 않는다** |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` → `docs/issues/049`의 ruling |
| **진행 상태 추적** | `.agent/plans/active/the-read-path-delivers-what-the-model-keeps.md` (gitignored, 메인 트리에만 있음) |

> **레인은 각자 worktree에서 돈다.** ExecPlan은 추적되지 않으므로 **이 문서가 레인의 계약이다.**
> 레인을 시작하는 사람은 `docs/issues/049`의 ruling과 이 문서를 읽으면 충분해야 한다.

---

## 0. 왜

`docs/issues/049`: 같은 모델이 같은 출력을 내면서 **806.61s 대 1.31s**, 614x. `DataModel.compute`는
양쪽 모두 0.36s다. **연산이 1.9%이고 데이터를 옮기는 것이 98%다.**

셋으로 갈라지고, 각각이 곱해진다 — 술어를 밀어넣을 수 없어 버릴 행을 읽고(153x), 그 행마다
식별 컬럼이 값 옆에 실려 오고(8.6x), 파일 자체가 100배 크다.

## 1. 오너 ruling — 요약만, 근거는 `docs/issues/049`

- **field는 표현식이고, dataset이 등록되는 자리에 선언된다.** `fields:`는 이미
  `id → 물리 컬럼`이었고 맨 컬럼은 축퇴된 표현식이므로, **오늘 존재하는 모든 등록이 그대로 유효**하다.
- **`DataRequirement`는 field id와 lookback이다.** `dataset_id` 없음(field id가 id다), `consumer_id`
  없음(선언하는 component가 곧 consumer이므로 프레임워크가 찍는다).
- **`instrument_field`는 선택이다.** 없는 dataset은 instrument 축이 없고, 선언된 instrument 목록이
  적용되지 않는다.
- **읽기 경로는 아무것도 검증하지 않는다.** 등록이 통과시킨 것은 그 뒤로 신뢰한다. 런타임에만
  드러나는 오류는 쫓지 않는다 — 터진 자리에서 터지고, 메시지는 손대지 않고 그대로 올린다.

## 2. 레인 — 파일 접촉으로 나눴다, 주제로 나누지 않았다

`src/vqapr/data/scan.py`가 이 캠페인의 **모든** 이슈에 걸린다. 그래서 레인은 접촉면이 좁아
rewrite 없이 병합 가능한 자리에서만 그었다.

| 레인 | 이슈 | worktree | 브랜치 | 의존 |
|---|---|---|---|---|
| **A** | `044` | `qlibx-wt-044` | `read-044-no-validation-on-read` | 없음 |
| **B** | `046` 후반 | `qlibx-wt-046b` | `read-046b-one-round-trip` | 없음 |
| **C** | `038` + `045`/`049` | `qlibx-wt-038-049` | `read-038-049-fields-are-expressions` | 없음 |
| **D** | `046` 전반 | `qlibx-wt-046a` | `read-046a-one-scan` | **C 병합 후 생성** |

**왜 다섯이 아니고 넷인가.** A와 B는 ruling과도 서로와도 독립이라 첫날부터 돌 수 있다.

**왜 C가 이슈 둘인데 한 레인인가.** 쪼개면 같은 코드를 두 번 옮긴다. `038`은
`instrument_field`를 선택으로 만들고 `045`/`049`는 `fields`가 표현식을 담게 하는데, **둘 다
`DatasetRegistration`·`declarations.py:414`·`workspace_codec.py`의 세 지점을 같은 편집에서
건드린다.** 스키마 변경을 두 병합으로 나누면 workspace 문서 마이그레이션도 두 번이다.

**왜 D가 뒤인가.** field가 공통 source 위의 표현식이 되기 전에는 융합할 대상이 없다. C에 접지
않고 따로 세운 이유는, **D가 실패해도 ruling을 되돌리지 않아야** 하기 때문이다.

### 레인 A — `044`: 읽기 경로는 아무것도 검증하지 않는다

`normalize_rows`(`src/vqapr/domain/rows.py:38`)가 같은 키 문자열 여덟 개에 같은 질문을 행마다
하고, `normalize_scalar`이 패키지가 방금 자기 parquet에서 읽은 셀을 다시 검사한다.

**지우는 게 아니라 옮긴다.** 등록이 정직하게 할 수 있는 유한성 검사는 등록 쪽으로, 이미 그 일을
하고 있는 `scan.positive_finite_when_true` 옆으로 간다. 이건 `035` addendum의 경고를 그대로
받는 것이다 — 검사를 **옮기지 않고** 읽기 경로 패스만 제거하면 평가당 1.6s를 조용한 NaN과
맞바꾼다.

**인수조건.** `normalize_rows`가 읽기 경로에서 사라진다. **NaN이 든 컬럼이 등록에서 거절되는
테스트**가 있고, 그것이 이 레인의 완료 조건이다(제거가 아니라 이동이 인수조건이다). 행 순서
계약은 건드리지 않는다 — `available_at` 다음 dataset의 key fields.

### 레인 B — `046` 후반: 선언된 입력당 왕복 한 번

`RowsLookback` 입력마다 `_rows_lower_bound`(`scan.py:640`) 다음 `observation_rows`(`scan.py:707`),
이름당 한 행을 돌려주는 데 두 statement, 각 ~50ms, 40세션 사다리 지점에서 119회.

**`scan.py:707`의 주석은 장식이 아니고 코드와 같이 움직인다**: 그 추정이 없으면 window가 매
callback마다 source 전체 역사 위에서 평가되고, exempt-instrument 분기는 bounded 쿼리가
unbounded 쿼리가 냈을 답을 내게 하려고 있다. 이걸 보존하지 않는 축약은 성능 옷을 입은 정합성
변경이다.

**인수조건.** 선언된 입력당 statement **2 → 1**, 쿼리 카운터로 측정. `046`의 사다리를 다시 돌려
floor를 보고한다.

### 레인 C — `038` + `045`/`049`: field는 표현식이고 instrument는 선택이다

캠페인의 중심. 한 편집으로:

1. `DatasetRegistration.instrument_field`가 `str | None`이 되고 `.of()`가 요구를 멈춘다
   (`src/vqapr/data/datasets.py:34`, `:72`).
2. `fields` 값이 표현식을 받는다. 맨 컬럼은 그대로 유효하고 오늘과 같은 뜻이다.
3. `observation_rows`가
   `SELECT <instrument> AS instrument, <available_at> AS available_at, <expr> AS <field-id> FROM source GROUP BY 1, 2`
   를 합성하고, **창 술어는 계속 프레임워크가 쓴다.** instrument 축이 없으면 instrument 술어와
   출력 컬럼이 둘 다 없다.
4. `DataRequirement`가 `(field_id, lookback)`이 된다. 프레임워크가 dataset을 찾고 `consumer_id`를
   찍는다 — `AccessRecord`에는 오늘과 똑같이 남는다.
5. field id는 workspace에서 유일하다. 충돌은 **이미 그 id를 가진 dataset을 이름 대며** 등록에서 거절.
6. 스키마는 등록 때 `DESCRIBE <query>`로 유도한다(duckdb 1.5.5에서 확인). 저자는 타입을 쓰지 않고,
   `show dataset`은 파일을 안 열고 답한다.
7. workspace 문서 마이그레이션. **write-forward, 이전 shape는 한 릴리스 동안 decode 가능**,
   move가 아니라 copy.

**인수조건.** `annual-fundamentals`가 long으로 등록된 `statement-facts` 위에서 wide 기준선과
**byte-identical** 출력을 낸다 — 여덟 필드 전부, **양방향 full anti-join, 어느 쪽도 0행**,
**타이밍을 읽기 전에** 확인한다. 600배 빠르면서 조금 다른 materialization은 빠른 모델이 아니라
다른 모델이다. 더해서: `instrument_field` 없이 등록되고 그 requirement가 run의 instrument 목록에
걸리지 않는 테스트(`038`의 `kimchi-ff5` 모양, `instruments:`에 factor id 없이), `DataRequirement`
시그니처 테스트, **그리고 기존 스위트 전부** — 오늘 유효한 등록은 하나도 안 깨져야 한다.

### 레인 D — `046` 전반: 한 스캔이 여러 field를 만족시킨다

요구는 읽기 전에 전부 선언되므로 같은 dataset 위 표현식들이 한 `SELECT`로 합쳐진다.
**이건 최적화가 아니라 전제조건이다** — requirement가 field 하나만 부르는 게 감당되는 이유가 이것이다.

**인수조건.** `ff_factors`의 선언된 입력 3개가 스캔 **3 → 1**.

## 3. 병합 순서와 worktree

```
C:/Users/chlje/DevProjects/qlibx             develop            통합
C:/Users/chlje/DevProjects/qlibx-wt-044      레인 A
C:/Users/chlje/DevProjects/qlibx-wt-046b     레인 B
C:/Users/chlje/DevProjects/qlibx-wt-038-049  레인 C
C:/Users/chlje/DevProjects/qlibx-wt-046a     레인 D — C 병합 시점에 생성
```

**병합 순서는 A, B, C, D.** A와 B는 작고 `scan.py` 접촉이 좁다. 먼저 붙이면 C가 그 결과 위로 한
번만 rebase한다(반대면 A와 B가 각각 rebase한다). **각 쌍에서 나중에 들어가는 쪽이 rebase한다** —
`scan.py`가 공유 파일이고 이걸 피하는 배치는 없다.

레인마다: `develop`에서 분기 → implementation record 하나 → `--no-ff` 병합. **병합 사이에
`develop`은 항상 green이어야 한다.**

- worktree마다 **자기 `uv sync`가 필요하다** (`.venv`는 트리별이다).
- **두 worktree가 같은 `.vqapr/`를 보게 하지 마라** — workspace 문서는 single-writer 저장소다.
- `.agent/plans/**`는 gitignored라 ExecPlan은 메인 트리에만 있다. 레인에서 필요하면 절대경로로 읽어라.

## 4. 게이트

| 게이트 | 명령 | 언제 |
|---|---|---|
| lint | `uv run ruff check src/` | 모든 레인, 병합 전 |
| fast suite | `PYTHONUTF8=1 uv run pytest tests/ -q` | 모든 레인, 병합 전. **1497 이상** |
| full incl. slow | `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` | 레인 C |
| slow, `-rs`로 따로 | `PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs` | 레인 C — 기록 `097`이 `-m ""`는 호출 이름일 뿐 무엇이 돌았는지 증명하지 않는다고 교정했다 |

**캠페인이 끝에 지는 숫자 하나:** `annual-fundamentals`, 1,600 instruments × 4 evaluations, long
등록, **806.61s 기준선 대비** — anti-join을 타이밍보다 **먼저** 돌린 상태로.

재현 하네스는 `kwam-enhanced-index/vqapr-performance-testbed/`이고 built wheel을 상대로 돈다.
`wide_experiment.py`가 614x 표와 anti-join을, `pivot_experiment.py`가 한 window 읽기를
(10.19s → 0.048s), `bench.py --stage datamodel`이 1.9%/48.6%/44.7% 분해를 낸다.

## 5. 하지 않을 것

- **`035`의 columnar accessor를 지금 결정하지 않는다.** 그 근거는 477,628행이 477,628개 dict가
  된다는 것인데, ruling 이후 측정 대상이 4,428,480셀에서 3,375셀이 된다. **레인 C 병합 후 재측정하고
  그때 정한다.** 지금 정하면 곧 없어질 읽기 경로에 대해 답하는 것이다.
- **field당 자유 SQL을 열지 않는다.** 표현식만. join이나 subquery가 필요한 field는 DataModel이다.
  실제로 막히는 사례가 나오면 그때 열되, **여는 순간 저자가 look-ahead를 쓸 수 없다는 성질을 잃는다** —
  구현 세부가 아니라 ruling 변경이다.
- **척추를 건드리지 않는다.** `optimize`, `plan_orders`, `Account.prepare_fill`,
  `Fill.__post_init__`, `ModelWindow`의 requirement 검사.
- **구조 리팩터링 Step 12–15를 여기서 하지 않는다.** 다른 캠페인이고 미승인 범위다.

## 6. 위험

| 위험 | 가장 이른 신호 | 대응 |
|---|---|---|
| **green tree, 옮겨진 지표, 틀린 숫자.** 이 repo에 두 번 기록돼 있고(`docs/issues/041`; `cli/run.py:170`) 직전 캠페인 안에서 한 번 더 났다(기록 `115` erratum) | 인수조건 tolerance가 느슨해지거나, 구조 작업 중 numeric baseline이 재생성됨 | 어떤 레인도 `settle_contract_hml.fixture.json`이나 showcase baseline을 재생성하지 않는다. 필요해 보이면 멈추고 escalate |
| **열리지 않는 workspace.** 레인 C가 문서를 마이그레이션하고 `_decode`는 forward reference를 검증하므로, 마이그레이션 후 revert하면 모든 명령이 실패한다 | 마이그레이션이 copy가 아니라 move | write-forward, 이전 shape 한 릴리스 decode 가능, copy |
| **표현식이 실제 데이터에 대해 너무 약함** | 레인 C 진행 중 저자가 막힘 | 문법을 넓히기 **전에** 막힌 사례를 `049`에 기록한다. 넓히면 look-ahead 성질을 잃으므로 ruling 변경이다 |
| **읽기 경로 검증 제거가 NaN을 조용히 통과시킴** — `035` addendum이 정확히 이걸 지목한다 | 레인 A가 등록 쪽 검사 없이 병합됨 | 레인 A의 인수조건은 제거가 아니라 **이동**이고, 등록 거절 테스트가 그것을 닫는다 |
| **레인 간 `scan.py` 충돌** | 두 레인이 같은 주에 `observation_rows`를 편집 | 순서 A, B, C, D. 나중에 들어가는 쪽이 rebase. **피할 수 없고, 받아들인다** |
