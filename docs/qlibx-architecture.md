# qlibx Architecture

## 1. 문서의 지위와 목적

이 문서는 `src/qlibx/`의 **현재 구현 구조(as-is)**를 기술한다. 코드에서 직접 도출했으며, 코드가
바뀌면 이 문서도 함께 갱신한다.

| 문서 | 지위 |
| --- | --- |
| [`qlibx-prd.md`](qlibx-prd.md) | Canonical product requirement. 무엇을 만들 것인가 |
| **이 문서** | 현재 구현된 구조. 실제로 무엇이 어떻게 연결되어 있는가 |
| [`implementations/`](implementations/) | 개별 변경의 이유·트레이드오프·검증 기록 |
| `references/qlibx/docs/qlibx-architecture.md` | **비권위적 old doc.** 아직 도달하지 않은 target architecture |

> **중요**: `references/`의 architecture 문서는 `entrypoints/`, `application/`, `contracts/`,
> `runtime/`, `capabilities/`, `adapters/` 같은 계층별 디렉터리를 전제한다. 현재 코드는 그 구조가
> **아니다**. 계층은 디렉터리 이름이 아니라 **import 방향**이 정의하고 `tests/test_architecture.py`가
> 강제한다. 디렉터리는 계층을 나누는 수단이 아니라 **커진 module을 쪼개는 수단**으로 쓴다
> (§7.1의 `alpha/` 참조). 두 문서가 충돌하면 이 문서와 코드가 우선한다.

이 문서를 읽는 AI agent에게:

- 절대 경로가 아닌 repo-relative 경로를 사용한다.
- §3의 dependency table과 §12의 guardrail은 기계적으로 검증 가능한 규칙이다.
- Public surface(§4)를 벗어난 것은 private이다. `_vendor/`는 절대 직접 import하지 않는다.

---

## 2. 한 장으로 보는 시스템

```mermaid
flowchart LR
    H["Human / coding agent"]
    H --> CLI["CLI<br/>qlibx ..."]
    H --> API["Python API<br/>import qlibx"]

    CLI --> APP
    API --> APP

    subgraph APP["qlibx package"]
        direction TB
        DATA["data plane<br/>discover · register · load"]
        RES["research plane<br/>alpha · strategy · catalog"]
        EXE["execution plane<br/>Qlib closed loop"]
        REP["reporting plane<br/>stored artifact → report"]
        DATA --> RES --> EXE --> REP
    end

    APP --> PROJ

    subgraph PROJ["user project (manifest-owned roots)"]
        direction TB
        SRC["data/<br/>read-only source"]
        GEN["data/qlibx/<br/>derived parquet"]
        ST[".qlibx/<br/>artifacts · registrations"]
        RR["qlibx-research/<br/>catalog · events · blobs"]
        EXT["qlibx-custom/<br/>project-local code"]
    end

    APP --> QLIB["Qlib 0.9.7<br/>execution authority"]
```

핵심 원칙 4가지:

1. **Qlib이 execution authority다.** 체결 수량·비용·포지션·NAV는 Qlib만 확정한다. qlibx는 두 번째
   bar loop를 만들지 않는다.
2. **User source는 read-only다.** qlibx가 쓰는 것은 manifest가 선언한 generated root뿐이다.
3. **Durable authority는 파일이다.** immutable manifest + append-only event가 진실이고,
   DuckDB는 언제든 재생성 가능한 projection이다.
4. **확장은 registry로 한다.** 설치된 패키지를 수정하지 않고 operation·policy·extension을 등록한다.

---

## 3. Module map과 dependency 규칙

### 3.1 계층

`src/qlibx/`는 30개 top-level module/package(45개 `.py` 파일)로 구성된다. 계층은 **import 방향**이
만들고, 그 규칙은 `tests/test_architecture.py`가 강제한다. **현재 intra-package import graph는
acyclic이다** (순환 없음).

큰 module은 package로 승격한다. Module을 package로 바꾸는 것은 import 관점에서 투명하므로
`from qlibx.alpha import X` 같은 public 경로가 그대로 유지된다(§7.2 참조).

```mermaid
flowchart TD
    subgraph L5["entrypoint / facade"]
        cli["cli"]
        init["__init__"]
        dataf["data"]
        agentf["agent"]
    end

    subgraph L4["composition / cross-capability"]
        ensemble["ensemble"]
        reporting["reporting"]
        extensions["extensions"]
        skill["skill"]
        profiles["profiles"]
        sm["strategy_manifest"]
        storage["storage"]
    end

    subgraph L3["capability"]
        catalog["catalog"]
        registration["registration"]
        discovery["discovery"]
        artifacts["artifacts"]
        research["research"]
        execution["execution"]
        portfolio["portfolio"]
        onboarding["onboarding"]
    end

    subgraph L2["project boundary"]
        project["project"]
    end

    subgraph LRC["vendor gateway (read)"]
        runcat["run_catalog"]
    end

    subgraph L1["domain / foundation"]
        alpha["alpha"]
        strategy["strategy"]
        documentation["documentation"]
        config["config"]
    end

    subgraph L0["kernel (intra-package 의존 없음)"]
        errors["errors"]
        requirements["requirements"]
        serialization["serialization"]
        optimization["optimization"]
        orthogonality["orthogonality"]
    end

    subgraph V["vendored (private)"]
        vendor["_vendor/<br/>qlib_engine · qlib_backend"]
    end

    cli --> L1
    cli --> L2
    cli --> L3
    cli --> sm
    dataf --> catalog
    dataf --> registration
    dataf --> discovery
    dataf --> profiles
    agentf --> documentation
    agentf --> onboarding
    agentf --> skill

    ensemble --> alpha
    ensemble --> research
    reporting --> runcat
    extensions --> alpha
    extensions --> artifacts
    extensions --> requirements
    skill --> alpha
    skill --> documentation
    storage --> artifacts
    storage --> research
    storage --> runcat

    catalog --> config
    profiles --> catalog
    profiles --> requirements
    sm --> catalog
    sm --> config
    sm --> execution
    sm --> project
    sm --> requirements
    sm --> serialization
    sm --> strategy
    registration --> config
    artifacts --> strategy
    artifacts --> serialization
    research --> orthogonality
    research --> serialization
    execution --> strategy
    execution --> runcat
    execution --> vendor
    runcat --> vendor
    vendor --> optimization
    portfolio --> optimization
    onboarding --> serialization

    alpha --> errors
    alpha --> requirements
    strategy --> serialization
    documentation --> errors
    project --> config
    config --> errors
```

### 3.2 전체 dependency table (기계 판독용)

`(none)`은 intra-package 의존이 없다는 뜻이다.

| module | depends on (intra-package) | external |
| --- | --- | --- |
| `errors` | (none) | — |
| `requirements` | (none) | — |
| `serialization` | (none) | pandas |
| `optimization` | (none) | cvxpy, numpy, pandas |
| `orthogonality` | (none) | pandas |
| `config` | errors | yaml |
| `project` | config, errors | yaml |
| `documentation` | errors | — |
| `alpha` | errors, requirements | pandas |
| `strategy` | serialization | pandas |
| `catalog` | config, errors, project | duckdb, pandas |
| `discovery` | errors, project | duckdb, pyarrow |
| `registration` | config, errors, project, serialization | pyarrow |
| `profiles` | catalog, config, errors, project, requirements | — |
| `strategy_manifest` (package) | catalog, config, errors, execution, project, requirements, serialization, strategy | pandas |
| `artifacts` | errors, project, serialization, strategy | pandas |
| `research` | errors, orthogonality, project, serialization | duckdb, pandas |
| `portfolio` | optimization | pandas |
| `run_catalog` | `_vendor` | — |
| `execution` | `_vendor`, errors, run_catalog, strategy | pandas |
| `onboarding` | errors, project, serialization | — |
| `extensions` | alpha, artifacts, errors, project, requirements | pandas |
| `ensemble` | alpha, research | pandas |
| `reporting` | run_catalog | pandas |
| `storage` | artifacts, project, research, run_catalog | — |
| `skill` | alpha, documentation, errors, serialization | — |
| `data` | catalog, discovery, profiles, registration, requirements | — |
| `agent` | documentation, onboarding, skill | — |
| `cli` | alpha, catalog, discovery, documentation, errors, extensions, onboarding, profiles, project, registration, skill, strategy_manifest | qlib |
| `__init__` | errors, project + 14개 public submodule(**lazy**, §4.1) | — |
| `_vendor` | optimization (kernel only) | qlib, duckdb, pandas, numpy, cvxpy, matplotlib, yaml |

가장 많이 의존되는 module: `errors` → `project` → `serialization` → `config`/`alpha`/`requirements`.
`errors`는 이제 `Stage` 타입도 제공하므로 `config`가 stage를 인자로 받을 수 있다(§12.3).

### 3.3 Dependency 규칙

```text
entrypoint (cli, __init__, data, agent)
  -> composition (profiles, ensemble, reporting, extensions, skill, storage)
    -> capability (catalog, research, execution, artifacts, ...)
      -> project boundary (project)
        -> domain (alpha, strategy, config, documentation)
          -> kernel (errors, requirements, serialization, optimization, orthogonality)
```

- **Kernel은 아무것도 import하지 않는다.** 새 의존을 추가하려면 그 module이 kernel이 아니라는 뜻이다.
- **`alpha`는 pandas와 kernel의 `errors`, `requirements` 외에 아무것도 모른다.** 순수 계산 도메인으로
  유지한다. `project`, `catalog`, `research`를 import하면 안 된다.
- **`_vendor/`는 `execution`과 `run_catalog`만 import한다.** 둘은 서로 겹치지 않는 절반을
  번역한다 — `run_catalog`는 저장된 run을 **읽고**, `execution`은 run을 **실행한다**. 다른
  module이 vendored 코드를 직접 참조하면 drift다.
- **`_vendor/`는 kernel만 import한다.** 현재 `qlib_engine/enhanced.py`가 `optimization`
  하나를 쓴다. 그 위 계층으로 올라가면 gateway test가 보지 못하는 순환이 생기므로
  `test_vendored_qlib_depends_only_on_the_kernel`이 막는다.
- **역방향 import 금지.** 표에서 아래 계층이 위 계층을 import하면 순환이 생긴다.

---

## 4. Public surface

패키지 밖에서 쓸 수 있는 것은 이 두 가지뿐이다.

### 4.1 Python API

```python
import qlibx

qlibx.__all__
# ['Project', 'QlibxError', 'agent', 'alpha', 'artifacts', 'data',
#  'ensemble', 'execution', 'extensions', 'portfolio', 'reporting',
#  'requirements', 'research', 'storage', 'strategy', 'strategy_manifest']
```

책임 기반의 얇은 facade다. `data`와 `agent`는 하위 module을 재수출하는 facade이고,
`storage`는 세 저장소를 가리키는 문이며(§11.4), 나머지는 실제 module이다.
`_vendor`는 public surface가 아니다.

**Submodule은 lazy하게 resolve된다.** `qlibx/__init__.py`는 `_SUBMODULES` 선언과 PEP 562
`__getattr__`만 가지므로 `import qlibx`는 이름을 지목하기 전까지 아무 capability도 로드하지
않는다. `import qlibx.alpha`와 `from qlibx import alpha` 둘 다 그대로 동작하고, 지목한 것만
로드된다.

| import | 비용 | 끌려오는 heavy dependency |
| --- | --- | --- |
| `import qlibx` | ~0.05s | 없음 |
| `import qlibx.reporting` | ~0.4s | duckdb · pyarrow · pandas (**qlib 아님**) |
| `import qlibx.execution` | ~1.2s | qlib · duckdb · pyarrow · pandas |

이것이 §11.3의 "reporter는 다시 실행하지 않는다"를 import 수준에서 성립시킨다. Report를
구성하려고 Qlib runtime을 로드하지 않는다.

> **불변식**: `import qlibx`는 qlib·cvxpy·duckdb를 로드하지 않으며 `__all__`의 모든 이름이
> 실제로 resolve된다. `tests/test_architecture.py`의
> `test_importing_the_facade_does_not_load_the_execution_runtime`과
> `test_facade_exports_exactly_what_it_can_resolve`가 강제한다.
> Lazy import도 의존이므로 layering test는 `_SUBMODULES`를 import graph에 합친다.

### 4.2 CLI

```mermaid
flowchart LR
    Q["qlibx"] --> P["project"] --> P1["init · status"]
    Q --> D["data"] --> D1["requirements · discover · inspect<br/>plan · register · catalog · preview"]
    Q --> QL["qlib"] --> QL1["status · requirements · plan"]
    Q --> STG["strategy"] --> STG1["requirements · plan · preview"]
    Q --> AL["alpha"] --> AL1["operations · operation NAME · plan NAME<br/>exposure-requirements · exposure-plan · budgets"]
    Q --> AG["agent"] --> AG1["skill · instruction"]
    Q --> EX["extension"] --> EX1["contracts · contract NAME"]
    Q --> DOC["docs · schema · examples · errors"]
```

전체 29개 leaf command. 각 subcommand는 선언되는 자리에서
`set_defaults(handler=...)`로 handler를 바인딩하고, `cli.dispatch`는 `args.handler(args)` 한 줄이다.
handler는 **출력할 값을 return만** 하며 JSON 인코딩·출력·에러 변환은 한 곳에 모여 있다.

> **불변식**: 모든 leaf command는 handler를 가져야 한다.
> `tests/test_cli.py::test_every_leaf_command_binds_a_handler`가 강제한다.

읽기 전용(mutation 없음): `project status`, `data requirements|discover|inspect|plan|catalog|preview`,
`qlib *`, `alpha *`, `extension *`, `docs`, `schema`, `examples`, `errors`.
쓰기: `project init`, `data register`, `agent skill --apply`, `agent instruction --apply`.

---

## 5. Project와 ownership boundary

`qlibx.yaml`(schema_version 1)이 유일한 진입점이다. 모든 경로는 여기서 resolve하고,
project root 밖으로 나가면 `PROJECT` stage 실패가 된다.

```mermaid
flowchart TB
    M["qlibx.yaml<br/>schema_version: 1"] --> R{"paths"}
    R --> C["config: config/qlibx<br/>user-owned"]
    R --> S["source_data: data<br/>user-owned · READ-ONLY"]
    R --> G["generated_data: data/qlibx<br/>qlibx-owned"]
    R --> ST["state: .qlibx<br/>qlibx-owned"]
    R --> RS["research: qlibx-research<br/>qlibx-owned"]
    R --> E["extensions: qlibx-custom<br/>user-owned"]
```

| root | 소유 | qlibx가 쓰는가 |
| --- | --- | --- |
| `config/qlibx/` | user | 아니오 (읽기만) |
| `data/` | user | **절대 아니오** |
| `data/qlibx/` | qlibx | 예 — registration 산출물 |
| `.qlibx/` | qlibx | 예 — artifacts, registrations |
| `qlibx-research/` | qlibx | 예 — research catalog |
| `qlibx-custom/` | user | 아니오 (읽고 실행만) |

User가 작성하는 config 파일의 정확한 경로:

| 경로 | 역할 |
| --- | --- |
| `qlibx.yaml` | project manifest. `schema_version` + `paths` |
| `config/qlibx/data/base.yaml` | catalog 진입점. source/dataset fragment 위치 선언 |
| `config/qlibx/data/sources.yaml` | `parquet_sources` — 물리 parquet 경로 |
| `config/qlibx/data/registrations.yaml` | source → canonical parquet 매핑 |
| `config/qlibx/data/datasets/*.yaml` | logical dataset (`kind: table` 또는 `matrix`) |
| `config/qlibx/execution.yaml` | 실행 profile. clock + role↔dataset 매핑 |
| `config/qlibx/strategies/*.yaml` | Strategy identity, fixed lookback, canonical pandas requirement |
| `config/qlibx/bindings/*.yaml` | Strategy/version별 registered dataset과 exact field mapping |

`Project.contained(path)`가 모든 경로 접근의 관문이다. Registration output은 추가로
`generated_data` 하위여야 하며(`DATA_REGISTRATION` stage), extension source는
`extensions` 하위여야 한다.

---

## 6. Data plane — 등록에서 로딩까지

```mermaid
flowchart TB
    A["data/ 사용자 파일"] -->|"qlibx data discover"| B["DataCandidate<br/>read-only 목록"]
    B -->|"qlibx data inspect"| C["DataInspection<br/>schema · sample<br/>+ unresolved_requirements<br/>+ required_user_questions"]
    C --> D{"사용자가 semantics를<br/>확인했는가?"}
    D -->|아니오| STOP["구조화된 중단<br/>추측 금지"]
    D -->|예| E["registrations.yaml 작성"]
    E -->|"qlibx data plan"| F["RegistrationPlan<br/>mapping · source hash · 가정"]
    F -->|"qlibx data register"| G["canonical parquet<br/>available_at · ticker · information"]
    G --> H[".qlibx/registrations/ID.json<br/>provenance"]
    G --> I["datasets/*.yaml<br/>logical dataset 선언"]
    I -->|"ConfigDrivenDataLoader"| J["load_table(as_of=t) / load_matrix(as_of=t)<br/>DuckDB 쿼리 · availability <= t"]
```

**설계 의도**: qlibx는 **시간·티커·값의 의미를 절대 추론하지 않는다.** `inspect`는 스키마와 샘플만
보여주고 미해결 질문 목록을 반환하며, 사용자가 확답한 뒤에만 registration YAML을 쓴다. Basic
registration은 information field를 opaque하게 보존한다. 컬럼 이름이 비슷하다는 이유로 특정
Strategy의 canonical field로 rename하지 않는다.

Canonical 형태는 `available_at` + `ticker` + 불투명한 information 컬럼의 long table이다.
`available_at`이 point-in-time 가시성을 지배하는 유일한 시간축이고, event/observation time은
명시적으로 선언할 때만 별도 `time_field`로 존재한다.

**`as_of`는 선택이 아니다.** `load_table`/`load_matrix`는 `as_of`를 keyword-only 필수 인자로
받는다. 이 패키지에서 인자 하나를 빠뜨렸을 때 **실패 대신 더 좋아 보이는 결과**가 나오는 지점은
여기뿐이므로, 안전한 쪽을 기본값이 아니라 문법으로 만든다.

```python
loader.load_table("market", as_of=decision_time)  # point-in-time
loader.load_matrix("market", as_of=decision_time)

loader.load_full_history("market", reason="registration smoke")  # 명시적 전체 이력
loader.load_full_history_matrix("market", reason="backtest input matrix")
```

Registration, schema inventory, operator preview, backtest input 구성은 정당하게 전체 이력이
필요하다. 그 선택을 **생략된 인자에 숨기지 않고** `reason`으로 호출 지점에 남긴다. 빈 `reason`은
`DATA_REGISTRATION` stage 실패로 거부한다. `qlibx data preview`는 `--as-of`를 주면
bounded, 안 주면 full-history로 동작하며 결과의 `availability` 필드가 어느 쪽이었는지 밝힌다.

`limit`은 `available_at`·`ticker` 정렬 뒤에 적용한다. 정렬 없는 `LIMIT`은 스캔 순서에 따라
매번 다른 행을 돌려주므로 preview가 registration의 재현 가능한 증거가 되지 못한다.

Registration은 원본 SHA256을 계획 시점과 기록 직전에 두 번 확인하며, 도중에 바뀌면 `DATA_REGISTRATION`
stage 실패가 된다. 쓰기는 staging → `replace`로 원자적이다.

`profiles.plan_execution_profile`은 논리 dataset을 Qlib 실행 role
(`execution_price`, `valuation_price`, `universe`, `tradable`, `volume`, `benchmark_weight`,
signed일 때 `observed`/`shortable`)에 매핑하고, 누락·비matrix·clock 불일치를 실행 전에 보고한다.

Strategy가 선택된 뒤 semantic mapping은 별도 binding 단계에서만 생긴다.

```mermaid
flowchart LR
    R["basic registration<br/>opaque fields: 시가 · 종가"] --> C["DataCatalog<br/>registered field inventory"]
    M["Strategy manifest<br/>open_price · close_price"] --> P["read-only Strategy plan"]
    C --> P
    P -->|"facts only; mapping unresolved"| A["generated skill / agent interview"]
    A -->|"user approval 후에만"| B["Strategy binding YAML<br/>open_price: 시가<br/>close_price: 종가"]
    B --> V["resolver validation + bounded preview"]
    V --> S["plain pandas Strategy"]
```

Manifest가 pandas kind, index, dtype/nullability, fixed row lookback과 semantic meaning을 소유한다. Binding은
Strategy ID/version, registered logical dataset ID와 canonical-to-registered field mapping만 소유한다.
따라서 binding에는 pandas contract, question text, `confirmation.status`를 반복하지 않는다. Core plan은
candidate mapping을 선택하거나 질문 문장을 생성하지 않고 missing role/field와 registered inventory만
반환한다. Generated skill이 mapping을 제안하고 user approval 후 YAML을 쓰는 정책을 소유한다.

---

## 7. Alpha plane — registry 기반 확장

signal operation과 weight scaling은 **분기문이 아니라 registry**로 관리한다.
새 operation 추가는 등록 한 번이고, dispatch·lineage·문서·생성 skill이 자동으로 따라온다.

```mermaid
flowchart TB
    subgraph REG["alpha.OPERATIONS · OperationRegistry"]
        BI["built-in 13개 (§7.2 표 참조)"]
        PL["project-local<br/>register_operation(OperationSpec(...))"]
        EXT["extension-backed<br/>signal_transform_operation(ref, impl)"]
    end

    REG --> AT["apply_transform<br/>단일 연산"]
    REG --> AP["apply_pipeline<br/>순차 합성"]
    AT --> TR["TransformResult"]
    AP --> TR
    TR --> LIN["lineage: tuple[OperationContract]<br/>step마다 id · version · parameters"]

    W["signed weights"] --> BP["alpha.BUDGET_POLICIES<br/>BudgetPolicyRegistry"]
    BP --> FX["fixed<br/>각 side를 budget까지 스케일"]
    BP --> FL["flexible<br/>budget은 상한 · 절대 올리지 않음"]
    BP --> PP["project-local<br/>register_budget_policy(...)"]
    FX --> BR["BudgetResult<br/>weights + used + leftover"]
    FL --> BR
    PP --> BR
```

### 7.1 alpha package 구조

`alpha`는 operation과 scaling rule이 계속 늘어나는 자리이므로 한 파일로 두지 않는다.
1014줄짜리 단일 module을 다음 package로 분할했다.

```text
alpha/
├─ __init__.py        public 재수출 — from qlibx.alpha import X 를 그대로 유지
├─ contracts.py       OperationContract · TransformResult (registry와 operation이 공유)
├─ registry.py        OperationSpec · dispatch · pipeline 합성
├─ budget.py          weight-scaling policy registry
├─ exposure.py        exposure 측정
└─ operations/        built-in operation, 작용 축별로 분리
   ├─ cross_sectional.py   rank · demean · zscore · winsorize · clip
   ├─ time_series.py       lag · rolling_mean · rolling_std · linear_decay · hump
   ├─ grouping.py          group_demean (명시적 group label을 요구)
   └─ selection.py         top_bottom · per_name_cap
```

**각 operation 파일은 구현과 `OperationSpec` 선언을 함께 소유한다.** 중앙 등록 표가 없으므로
새 operation family를 추가하는 일은 *새 파일 + `operations/__init__.py`에 import 한 줄*로 끝난다.
동기화해야 할 두 번째 장소가 존재하지 않는다.

`from qlibx.alpha import ...` 경로는 설치된 예제(agent가 그대로 복사하는 코드)의 계약이므로,
`__init__.py`가 전체 public surface를 재수출하여 **어느 파일로 옮기든 import 경로는 불변**이다.
`tests/test_architecture.py::test_public_module_paths_stay_importable`이 이를 강제한다.

### 7.2 설치된 built-in operation

정확한 등록 이름이다. 런타임 확인은 `qlibx alpha operations`,
개별 계약은 `qlibx alpha operation <name>`.

| 이름 | axis | 요약 |
| --- | --- | --- |
| `cross_sectional_rank` | date_by_ticker | `[-0.5, 0.5]` 중심 백분위 순위 |
| `cross_sectional_demean` | date_by_ticker | 날짜별 횡단면 평균 차감 |
| `cross_sectional_zscore` | date_by_ticker | 날짜별 표준화 (모집단 표준편차) |
| `winsorize` | date_by_ticker | 날짜별 상·하위 분위수로 clip |
| `clip` | date_by_ticker | 절대 상·하한으로 clip |
| `group_demean` | date_by_ticker_with_group | 그룹 평균 차감 (라벨 결측 → 출력 결측) |
| `lag` | time_by_ticker | 인덱스 위치 기준 시프트 |
| `rolling_mean` | time_by_ticker | 완전 윈도우 이동평균 |
| `rolling_std` | time_by_ticker | 완전 윈도우 이동표준편차 |
| `linear_decay` | time_by_ticker | 최근 관측에 가중이 큰 선형 가중 평균 |
| `hump` | time_by_ticker | 스텝 변화 제한 (결측은 limiter를 재시작) |
| `top_bottom` | date_by_ticker | 상위 `count`=+1, 하위 `count`=-1 |
| `per_name_cap` | date_by_ticker | 종목별 절대 가중 상한 |

`OperationSpec`은 **선언된 semantics와 구현을 한 객체에 담는다**: `axis`, `tie_behavior`,
`nan_behavior`, `minimum_observations`, `group_missing_behavior`, `selection_behavior`, `dtype`,
`parameters`, 공용 `CapabilityRequirement`, 그리고 `apply` 콜러블. 이 덕분에 네 가지가 자동으로
일관된다.

1. **Dispatch** — `apply_transform`/`apply_pipeline`이 registry를 조회한다.
2. **Lineage** — `OperationSpec.contract()`가 결과에 기록될 `OperationContract`를 만든다.
   extension이면 `implementation_digest`(source hash)까지 들어간다.
3. **Discovery** — `qlibx alpha operations`, `alpha_operation` schema, 생성된 skill의
   `references/alpha-operations.md`가 모두 같은 registry에서 나온다.
4. **Requirement plan/error** — `plan_operation`과 `apply_transform`이 같은 requirement evaluator를
   사용한다. `group_demean`의 explicit point-in-time group input이 첫 built-in 사례다.

선언되지 않은 parameter는 즉시 거부한다(`operation linear_decay does not accept parameters ['windwo']`).

**Budget 의미(PRD §8.4)**: `flexible`은 side budget을 상한으로 취급하고 절대 올려 스케일하지 않으며,
`BudgetResult.long_leftover`/`short_leftover`로 남은 예산을 관측 가능하게 남긴다. 하위 generic
module이 이 미사용 예산을 임의로 복원하거나 무관한 종목에 배분하면 안 된다.

---

## 8. Strategy plane — point-in-time 경계

```mermaid
flowchart LR
    MY["config/qlibx/strategies/*.yaml<br/>StrategyManifest"] --> CP["common CapabilityRequirements"]
    BY["config/qlibx/bindings/*.yaml<br/>StrategyBinding"] --> PLAN["plan_strategy_binding"]
    CAT["DataCatalog<br/>registered fields"] --> PLAN
    CP --> PLAN
    PLAN -->|"ready"| RES["resolve_strategy_inputs<br/>as_of + fixed lookback + rename"]
    RES --> PI["ResolvedStrategyInputs<br/>canonical pandas only"]
    PI --> INV["invoke_pandas_strategy"]
    CODE["qlibx-custom trusted callable<br/>def decide(*, universe, market_data, ...)"] --> INV
    INV --> OUT["pandas Series / DataFrame"]
```

`strategy_manifest.py`가 user project와 pure Strategy code 사이 adapter다. Immutable 객체의 책임은 다음과
같다.

| 객체 | 소유하는 것 | 소유하지 않는 것 |
| --- | --- | --- |
| `StrategyManifest` | ID/version, trusted callable ref, parameter, positive fixed-row lookback, canonical pandas input/field/output contract | registered field name, raw path, 질문 문구 |
| `StrategyBinding` | binding ID, Strategy ID/version, role→registered dataset, canonical→registered field mapping | dtype/layout/lookback 중복, confirmation status |
| `CapabilityPlan` | missing/satisfied role, exact reason, registered field inventory, effective config ID | semantic 추천, config write |
| `ResolvedStrategyInputs` | decision time에서 bound된 canonical pandas object와 binding/config identity | catalog/YAML/agent 객체 |

`qlibx.pandas_strategy`는 모든 manifest에 `universe` matrix requirement를 자동 상속한다. Manifest가 이를
다시 선언하면 실패한다. Adaptive compatibility API의 `StrategyDefinition.all_data_requirements`도
`universe`를 상속하며, `run_strategy_execution`은 별도 dataset으로 추론하지 않고 실제 execution
scenario의 universe를 각 decision context에 주입한다.

Plain Strategy는 qlibx base class를 상속하지 않는다. Callable keyword는 manifest의 canonical pandas
role과 ordinary parameter뿐이다. Loader는 source를 configured extension root 아래로 제한하고 source
digest 기반 module identity로 trusted project code를 로드한다. Invoker는 signature, input mutation과
pandas output을 검사한다. 이 검증은 schema boundary이지 malicious-code sandbox가 아니다.

Fixed lookback loop:

```mermaid
sequenceDiagram
    participant Q as Qlib decision clock / caller
    participant R as Strategy input resolver
    participant S as plain pandas Strategy
    loop each decision time t
        Q->>R: t + frozen manifest + binding
        R->>R: registered dataset load(as_of=t)
        R->>R: availability > t 제외 + 최근 N periods + canonical rename
        R->>R: dtype/null + universe ticker alignment
        R->>S: universe, declared pandas inputs, ordinary parameters
        S-->>Q: new pandas output
    end
```

Ticker 축은 **manifest가 선언한 pandas kind에서** 읽는다 (matrix면 columns, table이면 선언된
`ticker` index level). 데이터 모양에서 추론하면 안 된다 — "columns가 전부 universe 안에 있다"는
조건은 정확히 보고할 것이 없을 때만 참이므로, 그것으로 축을 판별하면 검사가 통째로 공회전한다.
선언된 nullability는 table의 named column과 matrix의 cell 양쪽에 적용한다.

Parent/child composition은 DI container나 runner injection을 요구하지 않는다. Parent callable은 이미 받은
bounded pandas object의 같거나 더 좁은 slice를 child callable에 직접 전달한다. Child가 config/catalog를
읽거나 더 긴 lookback을 요청할 API가 없으므로 pandas-only 경계가 access control이 된다. Adaptive
compatibility path의 `DecisionContext.child()`도 parent universe를 자동 상속하고 시간·컬럼·값·availability
축소만 허용한다.

`run_manifest_strategy_execution`은 resolver와 trusted callable을 run 시작 시 한 번 freeze하고,
`pandas_decision_program` adapter를 Qlib callback에 연결한다. 매 decision마다 registered inputs를 다시
point-in-time resolve하지만 manifest/binding plan과 field inventory validation은 반복하지 않는다. Adapter는
registered universe의 current row가 Qlib execution universe와 같은지도 확인하고, weight Strategy의 최신
pandas row만 Qlib target으로 제출한다.

기존 adaptive `DecisionContext`/`DecisionResult` 경로는 feedback, memory, checkpoint와 Qlib closed loop를
위해 유지한다. 이 경로에서 강제되는 불변식은 다음과 같다.

- **No look-ahead** — dataset은 `available_at` 행렬 또는 DatetimeIndex로 `decision_time`에서 잘린다.
  미래 관측이 섞이면 program 호출 전에 실패한다.
- **Universe base requirement** — 모든 `StrategyDefinition`은 universe를 상속하며 context에 없으면 호출
  전에 실패한다. Child는 parent universe를 기본 상속하고 필요하면 명시적으로 좁힌다.
- **Context 불변** — program 호출 전후 digest를 비교해 bounded context 변조를 검출한다.
- **Child는 부모를 넘을 수 없다** — `DecisionContext.child()`는 시간·컬럼 범위 축소만 허용하고,
  부모 관측값이나 availability metadata를 바꾸면 실패한다.
- **Child는 계좌를 못 바꾼다** — `evaluate_child`는 부모 account digest를 전후 비교한다.
- **Resume 동등성** — `run_decision_sequence`의 checkpoint 재개 결과가 무중단 실행과 같아야 한다.

식별자 3단계: `invocation_id`(동결된 입력) → `primary_result_id`(kind + payload + memory) →
`result_id`(+ diagnostics + intermediates). diagnostic만 달라져도 상위 식별자는 유지된다.

---

## 9. Research plane — publication protocol

```mermaid
flowchart TB
    B["begin()<br/>staging/SESSION/ATTEMPT/"] --> S["stage_frame / stage_json"]
    S --> PP["prepare_publication()<br/>manifest 작성 · prepared/ 에 기록"]
    PP -->|"publish_intent event"| IN["install_publication()<br/>blob을 content digest로 설치"]
    IN --> CM["commit_publication()<br/>설치 완전성 재검증"]
    CM -->|"publish_commit event"| DONE["PublishedResult"]
    CM -->|"이미 커밋됨"| CH["cache_hit event"]

    CR["크래시"] -.-> REC["recover_publications()"]
    REC --> IN
```

**단계를 나눈 이유**: 어느 지점에서 죽어도 복구 가능해야 한다. `prepared/`에 계획이 남아 있으면
`recover_publications()`가 install부터 다시 진행한다. 디렉터리가 존재한다는 사실만으로 완료로 보지
않으며, `commit_publication`은 모든 blob 해시를 다시 검증한 뒤에만 커밋 이벤트를 남긴다.

Durable authority와 projection의 분리:

```text
records/*.json (immutable manifest) + events/events.jsonl (append-only)  =  진실
catalog.duckdb                                                          =  재생성 가능한 projection
```

`rebuild_projection()`은 언제든 DuckDB를 버리고 다시 만들 수 있다.

**병렬 agent**: 이벤트 추가는 OS 파일 락(Windows `msvcrt` / POSIX `fcntl`)으로 직렬화한다.
`record_decision`은 `expected_version`을 요구하는 CAS이며, 낡은 버전이면 거부한다.
`_write_once`는 같은 내용이면 멱등, 다른 내용이면 `immutable content conflict`로 실패한다.

**성능 설계**: append-only 로그는 계속 자라므로 질문마다 재스캔하면 비용이 누적된다.
`_EventProjection.build()`가 **연산당 한 번** 로그를 접어 committed record/attempt, 진행 중 attempt,
최신 decision을 한 번에 만든다. 호출 간 캐싱은 **의도적으로 하지 않는다** — 병렬 agent가 그 사이에
append했을 수 있어 캐시는 정확성을 깨뜨린다.

---

## 10. Execution plane — Qlib closed loop

```mermaid
sequenceDiagram
    participant Q as Qlib scheduler / account
    participant B as execution.py bridge
    participant P as DecisionProgram
    participant E as Qlib exchange

    Q->>B: decision time + 직전 확정 상태
    B->>B: _bounded_strategy_data(decision_time)
    B->>P: DecisionContext(bounded data, 확정 feedback, account)
    P-->>B: DecisionResult(weight)
    B->>B: 가중치 검증 (long-only: 음수·합>1 거부<br/>signed: side exposure <= 1)
    B-->>Q: 검증된 target
    Q->>E: 주문 제출
    E-->>Q: 체결 수량 / 비용 / 차단 사유
    Q-->>B: 확정 feedback (다음 스텝에서만 관측)
```

**qlibx는 production bar loop를 소유하지 않는다.** 요청한 target이나 의도한 signed 수량을 실현
보유량으로 취급하지 않는다. 체결은 Qlib이 확정한다.

두 경로:

| | Path A — long-only / enhanced index | Path B — matched capitalization |
| --- | --- | --- |
| 진입 | `run_strategy_execution(signed=None)` | `run_strategy_execution(signed=...)` / `run_signed_execution` |
| 의미 | physical weight | signed weight |
| 상태 | Qlib account가 유일 권위 | Qlib composite + capitalization journal의 joint checkpoint |
| 지위 | production | **compatibility mode** |

Path B의 항등식 — 티커별로 `C = B + A`, `A = C - B` (A=signed active, B=matched baseline ≥ 0,
C=Qlib composite ≥ 0). `_signed_result_from_backend`가 매 실행마다 수량 항등식과 NAV
(`composite = baseline + active`)를 1e-8 허용오차로 대조하고, 어긋나면 `QlibxInternalError`를 던진다.
qlibx 자신의 장부가 서로 어긋난 것이므로 호출자가 유발할 수도 고칠 수도 없다 — §12.3의 두 번째
종류이고, agent vocabulary에 나타나지 않는 유일한 두 지점이다.

Path B는 borrow/locate/margin/recall/forced buy-in/borrow fee를 **모델링하지 않는다.**
`SignedExecutionResult.compatibility_limitations`가 이 사실을 결과에 담아 반환한다.

`ExecutionScenario` dataclass가 Qlib backend 입력 계약을 한 곳에 선언한다(16개 필드).
이전에는 두 함수가 각자 `SimpleNamespace`를 만들어 이미 미세하게 어긋나 있었다.

---

## 11. Artifact · Extension · Reporting

### 11.1 Artifact envelope

```mermaid
flowchart LR
    V["임의 값<br/>DataFrame · Series · JSON"] --> W["serialization.write_payload<br/>parquet 또는 json"]
    W --> ID["artifact_id = digest(identity)"]
    ID --> DIR[".qlibx/artifacts/RUN/ARTIFACT/<br/>envelope.json + payload"]
    DIR --> EXP["export_bundle()<br/>complete 만 이식 가능"]
    EXP --> IMP["import_bundle()<br/>해시 재검증"]
```

envelope는 producer identity, parent/input 계보, 시간 범위, axis/unit/currency/timezone,
payload digest, coverage/warning/diagnostics, status를 담는다. **다운스트림은 생산자가 built-in인지
project-local인지 알 필요가 없다.** 원자적 설치는 staging 디렉터리 → `os.replace`.

### 11.2 Extension contract

3개 계약이 있고 각각 워크플로 위치·입출력·검증을 소유한다.

| contract | 호출 위치 | 입력 → 출력 | 합성 |
| --- | --- | --- | --- |
| `signal_transform` v1 | signal 이후, budget/ensemble/execution 이전 | DataFrame → 동일 축 DataFrame | 예 |
| `exposure_analyzer` v1 | report 구성 이전 | ArtifactEnvelope + payload → AnalysisSection | 예 |
| `report_renderer` v1 | 최종 표현 단계 | ReportDocument → bytes/str | 아니오 |

`load_extension`은 extension root 하위 경로만 허용하고, source SHA256을 계산해 `ExtensionRef`에
담는다. `invoke_signal_transform`은 호출마다 입력 불변·축 동일·numeric-or-missing을 검증한다.

> **보안 경계 명시**: project extension은 **신뢰된 코드**다. 계약 검증은 스키마 검증이지
> malicious code sandbox가 아니다. 프로세스·파일시스템·네트워크 격리를 제공하지 않는다.

### 11.3 Reporting

```text
stored artifact  ->  AnalysisSection  ->  ReportDocument  ->  renderer  ->  output + manifest
```

- Report는 strategy·model·optimizer·backtest를 **다시 실행하지 않는다.**
- Renderer는 계산하지 않는다. `compose_report`가 선택·정렬만 하고, `render_report`는 표현만 한다.
- Report output은 canonical research artifact가 **아니다**
  (manifest의 `artifact_role`이 이를 명시한다).

### 11.4 저장소 진입점 (`storage.py`)

Project는 결과를 세 곳에 남기고, 셋은 서로 다른 물건이다. `ProjectStorage`는 그 셋을 합치지 않고
**한 문에서 가리킨다**.

```python
storage = ProjectStorage.from_project(project)
storage.artifacts   # ArtifactStore   — run-local content-addressed
storage.research    # ResearchCatalog — staged publication + event log
storage.runs(path)  # RunCatalog      — vendored Qlib run store (읽기 전용)
```

셋을 합치지 않는 이유는 셋이 다른 것이기 때문이다. `RunCatalog`는 vendored 코드이고 `_vendor`
gateway 2개 중 하나라, 합치면 `reporting`이 execution runtime에 다시 묶인다(§3.3). `runs`가
method이고 경로를 받는 것도 run catalog는 execution이 위치를 정하기 때문이다 — artifacts와
research의 root는 manifest가 선언한다.

기존 import 3개는 그대로 동작한다. 이것은 merge가 아니라 front door다.

> `runs`의 import는 지연시킨다. `_vendor.qlib_engine.store`를 artifacts만 원하는 호출자가
> 로드하지 않게 하기 위해서다. DuckDB는 아낄 수 없다 — `research`가 module scope에서 import한다.

---

## 12. 횡단 관심사

### 12.1 식별자와 직렬화 (`serialization.py`)

패키지의 모든 durable identity가 여기서 나온다. **두 가지 canonical form이 있고 용도가 다르다.**

| 함수 | 용도 | 비고 |
| --- | --- | --- |
| `digest_document(value)` | JSON 모양 metadata: manifest, config, plan | 인코딩 불가 값은 `str` fallback |
| `digest_dataset(value)` | pandas 구조를 가진 값: decision context, strategy result | index·columns·dtype·결측을 명시 인코딩 |
| `digest_file(path)` | 대용량 파일 | 1MB 블록 스트리밍 |
| `digest_text` / `digest_bytes` | 문자열 / 바이트 | — |
| `validate_name(name)` | 저장 payload 이름 | 소문자·숫자·`_`만 |
| `write_payload` / `read_payload` | 저장 payload 입출력 | `PayloadFormat`(`parquet`\|`json`) 하나로 통일 |

`digest_dataset`을 써야 할 곳에 `digest_document`를 쓰면 dtype이나 결측만 다른 두 프레임이
같은 해시로 충돌한다. 재현성 식별자에는 반드시 `digest_dataset`을 쓴다.

### 12.2 Capability requirement 계약 (`requirements.py`)

`CapabilityRequirements`가 capability ID/version과 `CapabilityRequirement` 목록을 선언한다. 각
requirement는 의미·axis·unit·currency·사용 목적·충족 규칙·availability·mandatory/optional·미충족
효과·derivation alternative·next command를 가진다. Literal user question은 core contract가 아니다.

```text
CapabilityRequirements
  + RequirementEvidence (capability adapter가 수집)
  -> evaluate_requirements()        # project/CLI 의존 없는 순수 판정
  -> CapabilityResolution
       -> CapabilityPlan            # read-only preflight
       -> QlibxError.context         # runtime gap, 같은 직렬화
       -> ExposureArtifact metadata # explicit incomplete result
```

Optional requirement는 `not_requested`, `satisfied`, `unsatisfied`를 구분한다. Exposure caller는
`requested_metrics`를 반드시 지정하고, 요청한 input이 없으면 기본적으로
requirement gap으로 실패한다. `allow_incomplete=True`를 명시한 호출만
`status="incomplete"`와 `UnavailableOutput`을 돌려받는다.

Execution profile의 이전 `ExecutionProfilePlan` 공개 형식은 제거했다.
`execution_profile_requirements`와 `plan_execution_profile`은 공용 `CapabilityRequirements`와
`CapabilityPlan`을 반환하며, `require_execution_profile`이 같은 resolution으로 runtime error를 만든다.

Strategy manifest도 같은 kernel로 adapt된다. `plan_strategy_binding`은 manifest requirement와 catalog
evidence를 evaluator에 넣고, `ready=false`일 때 registered field inventory를 plan parameter로 함께
반환한다. Core는 mapping을 추천하지 않는다. Generated skill은 그 사실을 읽어 user와 interview하고,
approval 뒤 binding을 작성한 다음 같은 plan을 재실행한다.

### 12.3 에러 계약 (PRD §5.6)

실패는 두 종류이고, 그중 하나만 agent에게 나간다.

| | `QlibxError` | `QlibxInternalError` |
| --- | --- | --- |
| 의미 | agent가 대응해야 하는 실패 | qlibx 자신의 invariant 위반 |
| 필드 | `stage` · `message` · `expected` · `context` · `requires_user_confirmation` | `message` · `context` |
| stage | 있음 | **없음** |
| `expected` | 있음 (필수) | **없음** |
| 이유 | 호출자가 유발했거나 대응할 수 있다 | 호출자가 유발할 수 없고 고칠 수도 없다 |

`stage`는 **user journey의 어느 단계에서 막혔는가**이지 어떤 종류의 규칙이 깨졌는가가 아니다.
규칙 종류는 core가 답할 수 있지만 agent가 쓸 수 없다 — 어느 skill을 열지 결정해 주지 못한다.

```text
ONBOARDING  PROJECT  DATA_REGISTRATION  UNIVERSE  STRATEGY_CONTRACT  STRATEGY_RUN
ALPHA  PORTFOLIO  EXECUTION  RESEARCH_RECORD  REPORTING
```

**Core는 수리를 처방하지 않는다.** `expected`는 계약이 요구한 것을 진술할 뿐이다. 수리 경로가
대개 하나가 아니기 때문이다 — numeric 연산이 문자열 때문에 `STRATEGY_RUN`에서 실패하면 Strategy
안에서 cast할 수도, registration으로 돌아가 preprocess할 수도 있고, 어느 쪽이 옳은지는 그 문자열의
의미에 달려 있어 core가 알 수 없다. 선택 기준은 stage별 skill이 소유한다.

```mermaid
flowchart LR
    F["실패"] --> Q["QlibxError<br/>stage · message · expected · context"]
    Q --> CLI2["CLI: JSON 출력 + exit 2"]
    Q --> AG2["agent: qlibx errors STAGE 로 단계·skill 조회"]
    AG2 --> SK["stage skill<br/>복수의 수리 경로와 선택 기준"]
    U["이름 조회 실패"] --> UN["errors.unknown_name(stage, ...)"]
    UN --> Q
    G["requirement gap"] --> RG["errors.requirement_gap(stage, ...)"]
    RG --> Q
    UC["user code 예외"] --> PT["errors.passthrough(stage, error, ...)"]
    PT --> Q
    I["invariant 위반"] --> II["QlibxInternalError<br/>agent vocabulary 밖"]
```

`errors.passthrough()`는 user code/user data에서 나온 예외를 **분류하지 않고** 원래 type과 message를
그대로 싣는다. 남의 `TypeError`가 "invalid"인지 "corrupt"인지 판정하는 것은 호출 안쪽에서 답할 수
없고, 시도하면 정확했던 유일한 설명을 잃는다.

`errors.unknown_name()`이 "등록되지 않은 이름" 실패를 한 모양으로 만든다 — agent는 어느
registry에서 실패했든 `context["available"]`만 보면 대안을 얻는다.

`errors.requirement_gap()`은 typed `CapabilityResolution.to_dict()`를 변경 없이 context에 넣는다.
따라서 agent는 capability마다 다른 error shape를 해석하지 않는다.

`config`는 네 단계를 섬기므로 stage를 인자로 받는다. 호출 module이 `for_stage(...)`로 한 번
바인딩하여 파일 맨 위에 단계를 선언한다. YAML 중복 키는 PyYAML 콜스택 안에서 발견되어 인자가
닿지 않으므로 `_loader_for(stage)`가 stage를 실은 loader subclass를 만든다.

> **불변식** (`tests/test_documentation.py`):
> 모든 raise가 선언된 stage를 지목하고(threading 허용, 단 80% 이상은 직접 명시),
> 모든 `QlibxError`가 `expected`를 넘기며,
> `expected`가 CLI 명령이나 "user에게 물어라"를 담지 않고,
> PRD §5.6의 stage 표와 `errors.STAGES`가 정확히 일치한다.

### 12.4 Agent onboarding

```mermaid
flowchart LR
    D["qlibx agent instruction --detect"] --> P["plan_instruction<br/>dry-run"]
    P --> A["apply_instruction<br/>managed block만 교체"]
    S["qlibx agent skill --output DIR"] --> SP["plan_agent_skill<br/>파일별 action"]
    SP --> SA["apply_agent_skill<br/>--force 없이는 사용자 내용 미덮어씀"]
```

`AGENTS.md`/`CLAUDE.md`는 `<!-- qlibx:managed:start -->` 마커 사이만 교체하며 사용자 내용을
보존하고, 반복 실행해도 블록이 중복되지 않는다. 계획 이후 파일이 바뀌면 `ONBOARDING`
stage 실패로 거부한다.

생성되는 skill 패키지에는 `references/alpha-operations.md`가 포함되는데,
**설치된 registry에서 렌더링**되므로 operation을 추가하면 skill이 자동으로 최신이 된다.

---

## 13. Storage layout (실제)

```text
user-project/
├─ qlibx.yaml                       # manifest — 유일한 진입점
├─ config/qlibx/                    # user-owned
│  ├─ execution.yaml                #   실행 profile (role ↔ dataset 매핑)
│  └─ data/
│     ├─ base.yaml                  #   catalog 진입점
│     ├─ sources.yaml               #   parquet source 선언
│     ├─ registrations.yaml         #   source → canonical 매핑
│     └─ datasets/*.yaml            #   logical dataset (table | matrix)
├─ data/                            # user-owned, READ-ONLY
├─ data/qlibx/                      # registration 산출 parquet
├─ qlibx-custom/                    # project-local extension
├─ qlibx-research/                  # ResearchCatalog state
│  ├─ events/events.jsonl           #   append-only 권위
│  ├─ records/<record_id>.json      #   immutable manifest 권위
│  ├─ blobs/<sha256>                #   content-addressed payload
│  ├─ staging/<session>/<attempt>/  #   미완료 작업
│  ├─ prepared/<attempt>.json       #   crash 복구용 publication plan
│  ├─ frozen/<bundle_id>.json       #   frozen run bundle
│  ├─ proposals/<id>.json
│  ├─ locks/                        #   OS 파일 락
│  └─ catalog.duckdb                #   재생성 가능한 projection
└─ .qlibx/
   ├─ artifacts/<run>/<artifact>/   #   envelope.json + payload
   └─ registrations/<dataset>.json  #   registration provenance
```

---

## 14. Testing map

144개 테스트. PRD §13 acceptance criteria와의 대응:

| PRD | 주요 테스트 |
| --- | --- |
| P0 agent onboarding | `test_agent_onboarding`, `test_documentation`, `test_cli`, `acceptance/test_p0_p1_agent_journey` |
| P1 data journey | `test_data_discovery`, `test_data_flow`, `test_execution_profile` |
| P2 StrategyAgent · no look-ahead | `test_strategy_agent`, `test_strategy_qlib_integration` |
| P3 signed alpha tool | `test_alpha_lineage`, `test_public_contracts` |
| P4 research history · parallel agent | `test_research_catalog`, `test_research_journey`, `test_orthogonality` |
| P5 ensemble · enhanced index | `test_ensemble_portfolio`, `test_ensemble_portfolio_journey`, `test_enhanced_optimizer` |
| P6 Qlib signed execution | `test_signed_execution_journey`, `test_qlib_closed_loop` |
| P7 local module · raw artifact | `test_artifact_extension_reporting_journey`, `test_reporting`, `test_execution_surface` |
| P8 capability requirement · interview | `test_requirements`, `test_execution_profile`, `test_alpha_lineage`, `test_cli`, `test_documentation` |

구조적 불변식을 지키는 테스트(회귀 방지용, mutation으로 검증됨):

- **`tests/test_architecture.py`가 §3의 계층을 강제한다** — 모든 module이 layer에 배정되어 있고,
  import는 아래 계층으로만 가며, kernel은 무의존이고, graph는 acyclic이며, `_vendor`는
  `execution`/`run_catalog`만 통하고 kernel 위로 올라가지 않으며, `reporting`은 `execution`을
  import하지 않고, `alpha`는 kernel의 `errors`/`requirements` 외에 의존하지 않으며,
  public import 경로가 살아 있다.
  - import graph 파서는 `from qlibx import x` 형태와 `_vendor/`, 그리고 facade의 lazy
    `_SUBMODULES` 선언까지 모두 본다. 한 가지 spelling이라도 빠지면 그 아래 test들이 그
    spelling에 대해 **조용히 무의미해지므로**, 파서의 커버리지가 곧 guardrail의 범위다.
- `import qlibx`가 qlib·cvxpy·duckdb를 로드하지 않고, `__all__`의 모든 이름이 resolve된다.
- `load_table`/`load_matrix`에서 `as_of`를 생략할 수 없고, 전체 이력 읽기는 `reason`을 요구한다.
- 모든 CLI leaf command가 handler를 가진다.
- 모든 raise가 선언된 journey stage를 지목하고 `expected`를 넘기며, `expected`가 수리 절차를
  지시하지 않는다. PRD §5.6의 stage 표와 `errors.STAGES`가 일치한다.
- 문서화된 예제의 keyword가 실제 signature에 바인딩된다(단순 `compile()`이 아니라).
- 등록된 모든 operation이 `alpha_operation` schema의 필수 필드를 갖는다.

§15의 guardrail 중 계층·확장 관련 항목은 이제 산문이 아니라 실행되는 계약이다. `alpha`에
`from qlibx.project import Project`를 추가하면 `alpha (layer 1) imports project (layer 2)`로 실패한다.

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
```

---

## 15. Architecture guardrails

다음은 drift로 간주한다.

**계층 위반**

- `alpha`가 `project`, `catalog`, `research`를 import한다 (순수 도메인이어야 한다).
- kernel module(`errors`, `requirements`, `serialization`, `optimization`, `orthogonality`)이
  intra-package 의존을 얻는다.
- `_vendor/`를 `execution`·`run_catalog` 외의 module이 직접 import한다.
- `_vendor/`가 kernel 위 계층을 import한다.
- `reporting`이 `execution`을 import한다 (읽기는 `run_catalog`를 쓴다).
- `qlibx/__init__.py`가 submodule을 eager하게 import해 `import qlibx`가 qlib을 끌어온다.
- intra-package import graph에 순환이 생긴다.

**확장성 위반**

- signal operation이나 budget policy를 registry가 아니라 `if/elif` 분기로 추가한다.
- operation을 추가하면서 contract 선언을 별도 dict에 이중으로 관리한다.
- CLI 명령을 `parser()`에 추가하면서 handler 바인딩을 빠뜨린다.

**계약 위반**

- 이름 조회 실패를 `QlibxError`가 아닌 raw exception으로 던져 CLI가 traceback을 낸다.
- `research`·`execution`·`artifacts`가 conflict·stale 실패를 raw `ValueError`/`RuntimeError`로
  던져 agent가 어느 단계에서 막혔는지 얻지 못한다.
- 선언되지 않은 stage를 지목하거나, PRD §5.6의 stage 표와 `errors.STAGES`가 어긋난다.
- `QlibxError`를 `expected` 없이 던진다 (그건 내부 결함이 잘못된 type을 쓴 것이다).
- `expected`에 CLI 명령이나 "user에게 물어라"를 담아 core가 수리 경로를 지시한다.
- 여러 유효한 수리 경로 중 하나만 제시한다 (core도, 생성된 skill도).
- User code/user data에서 나온 예외를 core의 분류로 덮어써 원래 type과 message를 잃게 한다.
- 내부 invariant 위반에 stage와 `expected`를 붙여 agent vocabulary에 넣는다.
- Data/universe requirement 위반을 등록 시점에 통과시킨 뒤 Strategy 실행 중에 발견하게 한다.
- 문서화된 예제가 실제 signature와 맞지 않는다.
- Plan과 runtime error가 서로 다른 requirement resolution을 반환한다.
- Optional output에서 `not_requested`와 `unsatisfied`를 같은 상태로 취급한다.
- Requirement declaration/resolution에 conversational question wording을 저장한다.
- Strategy binding에 manifest의 pandas contract, lookback 또는 confirmation status를 중복 저장한다.

**데이터·실행 위반**

- 컬럼 이름 유사성으로 시간·티커·값 semantics를 추론한다.
- Basic registration에서 Strategy-specific canonical field로 semantic rename한다.
- Strategy implementation이 project/catalog/registration/binding/runner/agent API를 읽는다.
- Strategy binding이 catalog에 없는 dataset ID나 raw path를 참조한다.
- 모든 Strategy에 상속되는 universe를 개별 manifest가 다시 선언하거나 runtime에서 추론한다.
- user source root에 쓴다.
- 요청 target이나 signed projection을 Qlib 실현 보유량으로 취급한다.
- Qlib scheduler 밖에 두 번째 production bar loop를 만든다.
- generic downstream이 flexible 미사용 예산을 임의로 복원한다.
- DuckDB projection만 있고 manifest/event가 없는 상태를 완료 증거로 취급한다.
- 읽을 수 없는 event log line을 건너뛰고 축소된 projection을 정상 결과로 반환한다.
- decision time에 `as_of` 없이 registered dataset을 읽는다
  (전체 이력이 필요하면 `load_full_history(reason=...)`로 명시한다).
- 선언된 matrix axis나 nullability를 `assert`로만 보증하거나 matrix input에서 건너뛴다.
- reporter가 strategy·optimizer·backtest를 다시 실행한다.
- extension 계약 검증을 malicious code sandbox라고 표현한다.

---

## 16. 알려진 격차와 다음 단계

정직하게 남겨둔 것들:

| 항목 | 현재 상태 |
| --- | --- |
| **Capability requirement contract (PRD §5.4/§5.5, P8)** | **구현됨.** 공용 declaration/evaluator/plan/error 타입, execution-profile 공개 migration, `group_demean`, exposure request/unavailable 구분, extension declaration, CLI/schema/generated skill을 제공한다. 상세는 아래 §16.1 |
| **Strategy manifest/binding (PRD §6.3/§7/P2/P8)** | **구현됨.** Project YAML manifest와 binding, inherited universe, registered-field plan, fixed-lookback resolver, plain pandas callable, CLI/schema/generated skill을 제공한다. 기존 adaptive API도 universe를 상속한다 |
| Beta estimation · residualization (PRD §8.2/§8.3) | **의도적으로 미구현.** 공용 requirement 기반은 준비됐지만 별도 작업으로 연기했다 |
| `reporting` → `execution` → `_vendor` 결합 | **해소됨.** `run_catalog` port가 저장된 run 읽기를 소유하고 `reporting`은 이제 `execution`을 import하지 않는다. `_vendor/qlib_engine/__init__`도 lazy가 되어 report 구성에 qlib runtime이 로드되지 않는다 |
| `ResearchCatalog` 크기 | 930줄. event log · blob store · publication protocol · proposal · lock을 한 클래스가 소유한다. 협력 객체로 분리하는 것이 자연스러운 다음 단계 |
| `strategy_manifest` 크기 | **해소됨.** package로 승격했다 — `contracts` · `loading` · `capability` · `resolution` · `invocation`, 최대 파일 251줄. `strategy`와의 이름 정리는 아직 남았다 |
| capability adapter 중복 | **해소됨.** `requirements`의 probe protocol(`Finding` · `gather_evidence` · `supplied_roles_probe` · `plan_capability`)로 접었다. `RequirementEvidence`를 만드는 곳은 이제 패키지 전체에서 `gather_evidence` 하나다 |
| 저장소 3개 | **부분 해소.** `ProjectStorage`(§11.4)가 진입점을 하나로 모으고 payload 입출력을 `serialization`이 공유한다. 다만 identity·lineage 모델은 여전히 셋이다 — `RunCatalog`는 vendored 코드이고 `_vendor` gateway 경계에 묶여 있어 합칠 수 없다. PRD §9.3의 cross-plane reuse는 아직 미완 |
| `references/`의 target architecture | `contracts/`·`runtime/`·`capabilities/`·`adapters/` 디렉터리 계층, ComponentRef, FrozenInvocationBundle, TemporalSemantics(revision/vintage), CostModelSnapshot, RiskModelSnapshot은 아직 구현되지 않았다. 현재는 flat module + import 방향으로 계층을 강제한다 |
| Path B (matched capitalization) | compatibility mode. borrow/margin/recall/fee 모델 아님 |

디렉터리 사용 원칙: **계층을 나누는 데 쓰지 않고, 커진 module을 쪼개는 데 쓴다.**

- 계층은 `tests/test_architecture.py`의 `LAYERS` 선언과 import 방향이 정의한다. 디렉터리 이름은
  Python에서 아무것도 강제하지 못하므로 계층 표현 수단으로 쓰지 않는다.
- 한 module이 커져 내부에 여러 관심사가 생기면 package로 승격한다(`alpha/`가 그 사례). Module →
  package 전환은 import 관점에서 투명하여 public 경로를 깨지 않는다.
- 다음 승격 후보는 `research`(930줄, event log · blob store · publication protocol이 한
  클래스에 있다)와 `strategy`(801줄)다. `documentation`은 error 계약이 stage 7 → 11개
  responsibility로 줄면서 800줄이 되어 급하지 않다.

### 16.1 Capability requirement contract 구현 (PRD §5.4/§5.5, P8)

PRD가 확정한 흐름은 이렇다.

```mermaid
flowchart LR
    A["agent: capability 실행 요청"] --> B{"requirement 충족?"}
    B -->|예| C["실행 → 결과"]
    B -->|아니오| D["requirement gap 보고<br/>미충족 항목 · 이유 · alternative<br/>field inventory · next command"]
    D --> E["agent layer: user와 interview"]
    E --> F["data registration (§6)"]
    F --> A
```

현재 public implementation:

| 요소 | 구현 | public surface |
| --- | --- | --- |
| 공용 선언 | `CapabilityRequirements` + `CapabilityRequirement` + `DerivationAlternative` | `qlibx.requirements`, `schema capability_requirement` |
| 순수 판정 | evidence와 requested optional set에서 `CapabilityResolution` 생성 | `evaluate_requirements` |
| read-only plan | declaration, resolution, parameters, warnings, limitations | `CapabilityPlan`, `qlibx qlib plan`, `qlibx alpha plan`, `qlibx alpha exposure-plan` |
| runtime error | plan resolution을 변경 없이 error context에 사용 | `errors.requirement_gap(stage, ...)` |
| execution profile | legacy `ExecutionProfilePlan` 제거, 공용 공개 계약으로 전면 이관 | `execution_profile_requirements`, `plan_execution_profile`, `require_execution_profile` |
| alpha operation | `OperationSpec.requirements`; `requires_groups` boolean 제거 | `group_demean`, project-local/extension-backed `OperationSpec` |
| exposure | 명시적 metric request, `not_requested`와 `unsatisfied` 구분 | `exposure_requirements`, `plan_exposure`, `ExposureArtifact` |
| agent interview | gap/inventory 해석 → mapping 제안 → user approval → binding/config → 동일 요청 재실행 | generated `SKILL.md` |

공용 evaluator는 catalog를 import하지 않는다. `profiles` 같은 capability adapter가 project/catalog에서
`RequirementEvidence`를 만들고, `alpha`는 이미 전달된 bounded runtime input에서 evidence를 만든다. 이
분리로 선언과 판정은 공통이지만 data access는 각 책임의 상위 계층에 남는다.

Requirement object에는 질문 문구가 없다. Agent는 resolution의 missing requirement, alternative와
capability-specific plan parameter(Strategy의 registered field inventory 등)에서 설명과 질문을 구성한다.
Core가 natural-language interview를 versioned domain data로 저장하지 않으므로 agent/model/locale별 표현을
바꿔도 requirement identity가 변하지 않는다.

Exposure는 호출자가 `requested_metrics`를 지정한다. 요청하지 않은 optional 항목은 `not_requested`이고,
요청했지만 input이 없는 항목은 `unsatisfied`다. 기본 실행은 structured error로 중단한다. 명시적인
`allow_incomplete=True`만 incomplete artifact를 허용하며, 이 경우에도 `status="incomplete"`와
`UnavailableOutput` 때문에 완전한 성공으로 표시되지 않는다.
