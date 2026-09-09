# 읽기 경로 캠페인 — 레인, 인수조건, 병합 순서

| | |
|---|---|
| **작성 시각** | 2026-09-01 KST (+09:00) |
| **기준 커밋** | `develop @ 4dd85975`. 이 문서의 모든 행 번호는 그 커밋 기준이다 |
| **트리 상태** | `develop@602e1b3c`에서 **1515 passed, 0 skipped, 14 deselected** · `uv run ruff check src/` → clean. **작성 당시 1497이었고 레인 A가 올렸다 — §4를 보라** |
| **앵커 이슈** | `docs/issues/archive/049` — **오너 ruling이 거기 있고, 이 문서는 그것을 재론하지 않는다** |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` → `docs/issues/archive/049`의 ruling |
| **진행 상태 추적** | `.agent/plans/active/the-read-path-delivers-what-the-model-keeps.md` (gitignored, 메인 트리에만 있음) |

> **레인은 각자 worktree에서 돈다.** ExecPlan은 추적되지 않으므로 **이 문서가 레인의 계약이다.**
> 레인을 시작하는 사람은 `docs/issues/archive/049`의 ruling과 이 문서를 읽으면 충분해야 한다.

---

## 0. 왜

`docs/issues/archive/049`: 같은 모델이 같은 출력을 내면서 **806.61s 대 1.31s**, 614x. `DataModel.compute`는
양쪽 모두 0.36s다. **연산이 1.9%이고 데이터를 옮기는 것이 98%다.**

셋으로 갈라지고, 각각이 곱해진다 — 술어를 밀어넣을 수 없어 버릴 행을 읽고(153x), 그 행마다
식별 컬럼이 값 옆에 실려 오고(8.6x), 파일 자체가 100배 크다.

## 1. 오너 ruling — 요약만, 근거는 `docs/issues/archive/049`

- **field는 표현식이고, dataset이 등록되는 자리에 선언된다.** `fields:`는 이미
  `id → 물리 컬럼`이었고 맨 컬럼은 축퇴된 표현식이므로, **오늘 존재하는 모든 등록이 그대로 유효**하다.
- **`DataRequirement`는 `(dataset_id, field_id)`와 lookback이다.** `consumer_id` 없음(선언하는
  component가 곧 consumer이므로 프레임워크가 찍는다).

  > **정정 — 오너가 2026-09-01에 유일성 절반을 뒤집었다.** 원래 이 줄은 *"field id와 lookback,
  > `dataset_id` 없음(field id가 id다)"*였고, `docs/issues/archive/049`의 ruling도 *"a field id is an id,
  > **unique in the workspace**"*라고 박혀 있었다. **실환경에서 거짓이다** — 레인 C가 재보니
  > dataset 27개 중 **field id 21개가 겹치고**, 대부분은 병렬 계열이 아니라 평범한 도메인 어휘다
  > (`fiscal_yyyymm`이 6개 dataset에 있는 것은 그냥 그 컬럼 이름이 그거라서다).
  >
  > **틀린 것은 "id를 두 번 말하지 않는다"가 아니라 그 아래 깔린 전제였다** — field id가 저자가
  > 고르는 id 공간이라는 것. 실제로는 벤더 어휘다. 049 본문이 그렇게 적는다:
  > *"the ruling's premise meeting a workspace built before it."* 구현을 먼저 하고 실환경에 대봤기
  > 때문에 잡혔다.
  >
  > 확정형은 `DataRequirement.of("statement-facts", "net_income", lookback=...)`이고, 등록에
  > `field_conflict` 거절도 workspace 전역 field index도 **없다**. resolution은 뒷절반만 묻는다 —
  > 지목된 dataset이 그 field를 노출하지 않으면 `observation_store.resolve.field_missing`이,
  > 무엇을 노출하는지와 함께. `consumer_id` 절반은 그대로 선다. 기록 `123`.
- **`instrument_field`는 선택이다.** 없는 dataset은 instrument 축이 없고, 선언된 instrument 목록이
  적용되지 않는다.
- **읽기 경로는 아무것도 검증하지 않는다.** 등록이 통과시킨 것은 그 뒤로 신뢰한다. 런타임에만
  드러나는 오류는 쫓지 않는다 — 터진 자리에서 터지고, 메시지는 손대지 않고 그대로 올린다.

## 2. 레인 — 파일 접촉으로 나눴다, 주제로 나누지 않았다

`src/vqapr/data/scan.py`가 이 캠페인의 **모든** 이슈에 걸린다. 그래서 레인은 접촉면이 좁아
rewrite 없이 병합 가능한 자리에서만 그었다.

| 레인 | 이슈 | worktree | 브랜치 | 의존 |
|---|---|---|---|---|
| **A** | `044` | ~~`qlibx-wt-044`~~ | ~~`read-044-no-validation-on-read`~~ | **병합 완료 `111c0342`**, 기록 `119`. worktree 제거됨 |
| **B** | `046` 후반 | ~~`qlibx-wt-046b`~~ | ~~`read-046b-one-round-trip`~~ | **병합 완료 `35b73229`**, 기록 `120`. worktree 제거됨 |
| **C** | `038` + `045`/`049` | ~~`qlibx-wt-038-049`~~ | ~~`read-038-049-fields-are-expressions`~~ | **병합 완료 `df571533`**, 기록 `123` |
| **D** | `046` 전반 | (worktree 없이, `step-04-one-scan-serves-an-alias`) | `step-04-one-scan-serves-an-alias` | **완료 — 기록 `136`, 2026-09-02** |

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
4. `DataRequirement`가 `(dataset_id, field_id, lookback)`이 된다. `consumer_id`는 프레임워크가
   찍는다 — `AccessRecord`에는 오늘과 똑같이 남는다.
5. ~~field id는 workspace에서 유일하다.~~ **철회됨(§1 정정 참조).** field id는 **dataset 안에서만**
   유일하고, 겹친다고 등록을 거절하지 않는다. workspace 전역 field index도 만들지 않는다.
   부수적으로, 유일성 때문에 프레임워크가 run record 봉투 컬럼과 allocation `weight`를 dataset id로
   한정하던 것도 같이 풀린다 — 피할 충돌이 없으므로 `weight`·`run_id`를 그대로 노출한다.
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
- **`data/`를 메인 트리에서 junction으로 걸어라.** gitignore된 210MB 로컬 산출물이라 새 worktree엔
  없고, 없으면 테스트 5개가 **조용히 skip된다** — `passed`만 보면 안 보인다. 레인 H가 실제로 그
  상태로 green을 보고했다. 명령은 `mklink /J`이고 인자는 `<worktree>/data`와 메인 트리의 `data`다
  (Windows에서 junction은 관리자 권한이 필요 없다). `.gitignore:17`의 `/data/`가 덮으므로 status를
  더럽히지 않는다. **읽기 전용으로만 쓴다** — 모든 worktree가 같은 디렉터리를 본다.
- **두 worktree가 같은 `.vqapr/`를 보게 하지 마라** — workspace 문서는 single-writer 저장소다.
- `.agent/plans/**`는 gitignored라 ExecPlan은 메인 트리에만 있다. 레인에서 필요하면 절대경로로 읽어라.

## 4. 게이트

| 게이트 | 명령 | 언제 |
|---|---|---|
| lint | `uv run ruff check src/` | 모든 레인, 병합 전 |
| fast suite | `PYTHONUTF8=1 uv run pytest tests/ -q -rs` | 모든 레인, 병합 전. **고정 하한을 쓰지 말고, 분기한 커밋에서 직접 재서 비교하라** — 아래 |
| full incl. slow | `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` | 레인 C |
| slow, `-rs`로 따로 | `PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs` | 레인 C — 기록 `097`이 `-m ""`는 호출 이름일 뿐 무엇이 돌았는지 증명하지 않는다고 교정했다 |

> **하한을 숫자로 박지 마라 — 이 문서가 그 실수를 이미 한 번 했다.** 작성 시점의 1497을
> "1497 이상"으로 적어 두었더니, 레인 A가 그것을 1515로 올린 뒤 레인 H가 **1512 passed + 5
> skipped**를 green으로 판정했다. 통과가 3개 줄었는데 하한이 낡아서 가려졌다. 이건 이 캠페인
> §6의 첫 번째 위험(*green tree, 옮겨진 지표*)이 **인수조건 자신에게서** 난 것이다.
>
> **대신 이렇게 한다.** 레인은 자기가 분기한 커밋에서 스위트를 한 번 돌려 기준선을 직접 재고,
> 병합 전 수치를 그것과 비교한다. **`-rs`를 항상 붙인다** — skip은 돌지 않은 테스트이고,
> `passed`만 보면 skip으로 새어 나간 것이 통과 감소로 보이지 않는다. 기록 `097`이 같은
> 취지로 `-m ""`를 교정했다.

**캠페인이 끝에 지는 숫자 하나:** `annual-fundamentals`, 1,600 instruments × 4 evaluations, long
등록, **806.61s 기준선 대비** — anti-join을 타이밍보다 **먼저** 돌린 상태로.

재현 하네스는 `kwam-enhanced-index/vqapr-performance-testbed/`이고 built wheel을 상대로 돈다.

> **2026-09-02 (기록 `136`): 그 디렉터리는 더 이상 없다.** `kwam-enhanced-index/` 아래 어디에도
> `wide_experiment.py`·`pivot_experiment.py`·`bench.py`·`probes.py`가 없다. 806.61s 기준선은 이 하네스로는
> 재측정할 수 없고, 아래 숫자들은 그 세션의 기록으로만 남는다. 레인 D의 인수조건은 통계로 잰다 —
> alias 하나의 field 수와 무관하게 statement 하나 — 그리고 `ff_factors`의 실제 모양(alias 3개, dataset 3개,
> field 2+1+3)에서는 콜백당 6 → 3이다. "3 → 1"은 `049`가 alias 규칙을 정하기 전의 표현이다.
`wide_experiment.py`가 614x 표와 anti-join을, `pivot_experiment.py`가 한 window 읽기를
(10.19s → 0.048s), `bench.py --stage datamodel`이 1.9%/48.6%/44.7% 분해를 낸다.

> **측정하기 전에 읽을 것 — 레인 B가 셋 다 부딪혔다.** 근거와 숫자는 기록 `120`에 있다.
>
> 1. **testbed의 `probes.py`가 develop과 어긋나 있었다.** `public._freeze_record`와
>    `public.load_strategy_model`은 기록 115–117이 `vqapr.flow.orchestration`으로 옮겼고,
>    `store.normalize_rows`는 레인 A가 지웠다. 고치기 전에는 **모든 측정이 `AttributeError`로
>    죽는다.** 설치된 빌드에서 seam을 찾도록 고쳐 뒀지만 **커밋되지 않았다** — 다른 repo다.
> 2. **연구 패널이 레인 A 이후 등록되지 않는다.** `equity_daily.parquet`에 `+inf` 82행이 있다
>    (`A065180`, 2015-01~04, `adj_factor = 0`). 레인 A의 `check_values`가 **옳게** 거절한다.
>    `KWAM_PERF_PREPARED`로 그 82행만 뺀 스냅샷을 향하게 하면 측정은 계속할 수 있다(나머지는
>    하드링크, 같은 ZSTD·row group). 연구 환경의 `prepare.py`는 별개로 고쳐야 한다.
> 3. **book의 wall time으로 몇 %를 재려 하지 마라.** 같은 빌드가 pass마다 ±20% 흔들렸고,
>    12분 떨어져 돈 두 arm은 20% 이득을 **허위로** 보고했다(그 사이에 파이프라인이 하나 더
>    떴다). rung마다 두 arm을 붙여 돌리고 순서를 교대하라. 그래도 안 갈리면, 바뀐 호출 하나를
>    직접 재는 하네스를 쓰는 편이 낫다 — 레인 B는 그렇게 −14~16%를 6쌍에서 확인했다.

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
| **green tree, 옮겨진 지표, 틀린 숫자.** 이 repo에 두 번 기록돼 있고(`docs/issues/archive/041`; `cli/run.py:170`) 직전 캠페인 안에서 한 번 더 났다(기록 `115` erratum) | 인수조건 tolerance가 느슨해지거나, 구조 작업 중 numeric baseline이 재생성됨 | 어떤 레인도 `settle_contract_hml.fixture.json`이나 showcase baseline을 재생성하지 않는다. 필요해 보이면 멈추고 escalate |
| **열리지 않는 workspace.** 레인 C가 문서를 마이그레이션하고 `_decode`는 forward reference를 검증하므로, 마이그레이션 후 revert하면 모든 명령이 실패한다 | 마이그레이션이 copy가 아니라 move | write-forward, 이전 shape 한 릴리스 decode 가능, copy |
| **표현식이 실제 데이터에 대해 너무 약함** | 레인 C 진행 중 저자가 막힘 | 문법을 넓히기 **전에** 막힌 사례를 `049`에 기록한다. 넓히면 look-ahead 성질을 잃으므로 ruling 변경이다 |
| **읽기 경로 검증 제거가 NaN을 조용히 통과시킴** — `035` addendum이 정확히 이걸 지목한다 | 레인 A가 등록 쪽 검사 없이 병합됨 | 레인 A의 인수조건은 제거가 아니라 **이동**이고, 등록 거절 테스트가 그것을 닫는다 |
| **레인 간 `scan.py` 충돌** | 두 레인이 같은 주에 `observation_rows`를 편집 | 순서 A, B, C, D. 나중에 들어가는 쪽이 rebase. **피할 수 없고, 받아들인다** |
