# Research-Model vocabulary and module directory semantics

## Intent

PRD §8.2는 reusable intermediate research data를 만드는 component를 일관되게 **Model**이라 부른다.
Built-in 구현도 이미 `ForwardReturnLabelModel`이었다. 그러나 그것이 구현하는 protocol만
`MaterializationOperation`이라는 다른 어휘를 썼기 때문에, 코드에서 "Model"이라는 개념을 찾을 수 없었다.

동시에 세 디렉토리가 이름으로 역할을 전달하지 못했다. `operations/`는 의미가 없었고,
`kernel/`은 `clock.py` 하나만 담고 있었으며, `production/`은 docstring 한 줄짜리 빈 package였다.
또한 `operations/`, `extensions/`, `flow/`는 이름만 보면 모두 "여기서 뭔가 실행된다"로 읽혀
계약 / 등록 / 순서라는 세 층의 구분이 드러나지 않았다.

PRD는 file layout과 Python public name을 요구사항에서 명시적으로 제외한다
(§Document interpretation). 따라서 이 변경은 product decision이 아니라 이해 비용을 줄이는 rename이다.

## Observable outcome

동작, 계약, artifact schema, 수치 결과는 바뀌지 않는다. 공개 표면의 이름과 모듈 경로만 바뀐다.

| 이전 | 이후 |
|---|---|
| `MaterializationOperation` | `ResearchModel` |
| `MaterializationOutputContract` | `ModelOutputContract` |
| `MaterializationInvocation` | `ModelInvocation` |
| `MaterializationComputationError` | `ModelComputationError` |
| `MaterializationFlow` | `ModelFlow` |
| `MaterializationRunResult` | `ModelRunResult` |
| `MaterializeView` | `ModelView` |
| `ViewGate.materialize_view()` | `ViewGate.model_view()` |
| `qlibx.operations.materialization` | `qlibx.contracts.model` |
| `qlibx.operations` | `qlibx.contracts` |
| `qlibx.flow.materialization` | `qlibx.flow.model` |
| `qlibx.kernel` | `qlibx.runtime` |
| `qlibx.production` | 제거 |

`QlibxProject.materialize()`는 변경하지 않는다. `materialize`는 행위이고 PRD가
"materialized research data"로 계속 사용한다. 행위자만 Model 어휘를 갖는다.

`SampleMaterializer`, `SampleMaterializationResult`, `QlibxProject.materialize_sample()`은
sample 파일 materialization이라는 별개 개념이므로 그대로 둔다.

## Responsibilities and flow

`contracts/`는 사용자가 구현하는 계약만 담는다: `strategy.py`(StrategyOperation),
`model.py`(ResearchModel와 built-in), `artifacts.py`(artifact I/O 선언). 파일은 분할하지 않았고
이름만 바뀌었다.

이로써 세 층의 구분이 디렉토리 이름에서 드러난다.

- `contracts/` — 사용자가 **무엇을** 구현하는가
- `extensions/` — 사용자가 쓴 파일을 **어떻게** 검증·등록하는가
- `flow/` — 그것들을 **언제 어떤 순서로** 호출하는가

`runtime/`은 `kernel/`이 담던 aware clock과 Event를 그대로 담는다. 이름만 실제 크기와 역할에 맞췄다.

`production/`은 제거했다. Future OMS boundary의 부재는 빈 package가 아니라
`docs/qlibx-prd.md` §14와 `docs/oms-future-plans.md`가 기술한다.
`tests/test_architecture.py`의 layer dependency map에서도 해당 항목을 제거했으며,
나머지 import 방향 계약은 이름만 갱신하고 관계는 그대로 유지했다.

## Alternatives and trade-offs

`QlibxModel` → `QlibxRecord` 치환을 함께 검토했다. `Model`이라는 단어를 연구 개념 전용으로
해방하면 중의성이 완전히 사라지지만, 245곳 참조와 165개 상속 클래스가 함께 움직인다.
제품 소유자가 이번 범위에서 제외하기로 결정했으므로 `QlibxModel`은 그대로 두었다.
따라서 "Model"은 여전히 Pydantic base와 연구 개념 두 뜻을 갖는다. 구체 클래스는
`XxxModel` 접미로 구분되므로 실사용에서 혼동은 제한적이다.

`operations/`를 `strategy/`와 `model/` 두 디렉토리로 쪼개는 안도 검토했으나,
`artifacts.py`가 Strategy 소비와 Model 생산 양쪽에 걸쳐 있어 소속이 모호해진다.
하나의 `contracts/`로 두는 편이 경계가 선명하다.

Compatibility shim은 두지 않았다. `docs/module-map.md`가 이미 그 방침을 기록했고
직전 `specs/`·`view/` 이동도 같은 방식이었다.

## Validation

- `.venv/Scripts/python.exe -m pytest tests/ -q` -> **298 passed, 2 failed**.
  두 실패는 `tests/test_data_source_audit.py`이며 `data/preprocessed/sector_classification.parquet`의
  행 수가 기록된 계약과 다르다는 사전 조건이다. 변경 전 tree(`git stash`)에서도 동일하게 실패함을
  확인했으므로 이 변경과 무관하다.
- `.venv/Scripts/python.exe -m ruff check src/ tests/ showcases/` -> All checks passed
  (rename으로 깨진 import 정렬 38건은 `--fix`로 정리).
- `.venv/Scripts/python.exe -c "import qlibx"` -> 성공.
- `tests/test_architecture.py`의 layer import 방향 계약이 갱신된 이름으로 통과한다.
- `tests/test_document_traceability.py`, `tests/test_contracts.py` 통과.
- Sample 계열 잔존 확인: `SampleMaterializer`, `SampleMaterializationResult`,
  `materialize_sample`이 변경되지 않았음을 grep으로 검증했다.

`ruff format --check`는 68개 파일을 reformat 대상으로 보고하지만 이는 변경 전 HEAD에서도
동일한 사전 조건이다(저장소는 `ruff check`만 사용한다). 이번 변경에서 포맷은 건드리지 않았다.

## Remaining limitations

- `QlibxModel`이 여전히 "Model" 단어를 점유한다(위 trade-off 참조).
- `evidence/`와 `flow/`의 이름은 이번 범위 밖으로 남겼다. `evidence/`는 artifact envelope과
  catalog backend를 담으므로 `catalog/`가 더 직관적이라는 관찰이 있으나 별도 결정 대상이다.
- `flow/daily.py`(2,314줄) 분할은 여전히 보류다. 근거는 `docs/module-map.md`에 있다.
