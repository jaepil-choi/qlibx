# 269 — data가 읽기를 전부 들고, 체결 시각 규칙은 파일을 읽지 않고, 기록이 자기 표의 이름을 안다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M3 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §6 · §11.3 · §13 · 부록 A, 오너 결정 D10 · D11 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `268`(domain 한 개념 한 모듈), `183`(shapes.py), `185`(체결표는 데이터), `205`(FillRule의 at · after · within), `234`(한 문) |

---

## 왜 이 변경이 있는가

`domain/shapes.py`는 "데이터가 컴포넌트까지 오는 모양"이라는 이름 아래 일곱 가지를 모았는데, 그중 둘은 모양이 아니었다:
`Grain`은 dataset 등록의 속성이고 `RecordChunk`는 기록 버퍼다. 남은 넷 중 `CrossSection`과 `Series`는 panel의 행과
열이다. 진짜 개념은 둘 — 넓은 모양(panel)과 긴 모양(`Observation`)이다. 그리고 `data/` 안의 이름 셋이 하는 일을 말하지
않았다: `validation.py`의 함수는 `verify_source` · `require_verified`인데 모듈은 validation이었고, `sources.py` ·
`windows.py`는 안의 주 클래스와 수가 달랐다.

체결 시각 규칙(`FillRule`)은 도메인 규칙인데 `exchange/conventions.py`에서 `vqapr.data`를 import했다. 규칙의 두 메서드가
체결표 소스를 직접 스캔했기 때문이다. 그리고 보고서(`report/record.py`)가 프레임워크 표의 이름을 알려고 엔진
(`flow/run/context.py`)을 import했다 — 기록을 읽는 쪽이 기록을 쓰는 엔진에 기대고 있었다.

## 무엇이 어떻게 바뀌었는가

| 새 자리 | 무엇이 들어왔나 |
|---|---|
| `data/dataset.py` | `datasets.py` + `Grain` |
| `data/requirement.py` | `requirements.py` + `resolution.py` |
| `data/panel.py` | 그대로 + `CrossSection`(panel의 행) · `Series`(panel의 열) |
| `data/observation.py` | `Observation`(긴 표의 한 행) |
| `data/source.py` · `verification.py` · `window.py` | `sources.py` · `validation.py` · `windows.py`의 이름만 바꿈 |
| `data/execution_table.py` | `exchange/execution_table.py` — 체결표는 등록된 데이터다(record `185`). 거래소 profile들이 쓰는 요청 검사 셋은 컴포넌트 단계(M5)에서 `component/exchange/base.py`로 간다 |
| `record/chunk.py` | `RecordChunk` |
| `domain/fill.py` | + `FillRule` · `ExactExecutionTarget` · `ExecutionHorizon` · `parse_duration` (`exchange/conventions.py`) |
| `domain/identifiers.py` | + `require_identifier` — `Observation`과 `CrossSection`이 함께 쓰던 비공개 검사 `_identifier`. 메시지는 한 글자도 같다 |
| `record/schema.py` | + 프레임워크 표 이름 `DEFAULT_TABLE_PREFIX` · `WEIGHT_TABLE` · `ACCOUNT_TABLE` · `MONITORING_TABLE` · `FILL_TABLE` · `FRAMEWORK_TABLES` |

사라진 것: `domain/shapes.py`(와 아무도 쓰지 않던 `Panel` Protocol), `data/datasets.py` · `requirements.py` ·
`resolution.py`, `exchange/conventions.py`.

- **`FillRule`은 파일을 읽지 않는다.** `select_target`은 이제 언제나 horizon(체결표의 후보 시각들)을 받는다.
  `build_horizon`은 `FillRule`에서 빠졌고, 스캔은 `ExecutionTable.build_horizon`이 직접 한다. horizon 없이 부른
  `ExecutionTable.select_target`은 **예전 fallback과 같은 질의**(`scan.candidate_instants(source, decision_time=판단 시각,
  end_time)`)로 horizon을 만들어 넘긴다 — 후보 집합이 같으므로 고르는 시각이 같다. 새 `ExecutionHorizon.of(candidates)`가
  스캔 결과를 UTC로 맞추고 정렬한다. `FillRule`은 이제 층 0(`domain/fill.py`)에 있다.
- **기록이 자기 표의 이름을 안다.** 네 프레임워크 표의 id는 `record/schema.py`의 상수이고, 엔진(`flow/run/context.py`의
  `DEFAULT_TABLES`)은 그 이름으로 열 명세를 짓는다. `report/record.py` · `cli/export.py` · `cli/run.py`는 `record.schema`에서
  이름을 읽는다 — 보고서는 더 이상 엔진을 import하지 않는다. 같은 이름이 `run_state.py` · `orchestration.py`에 따로 정의되던
  것도 사라졌다.
- 테스트가 문자열로 쓰는 사용자 컴포넌트 두 곳(`test_strategy_registration.py`, `test_preflight.py`)이 `vqapr.data.requirements`를
  import했다 — `vqapr.public`으로 바꿨다(record `268`과 같은 규칙).
- `scripts/evidence_*.py` 셋의 import도 새 경로로 (옮긴 모듈을 읽는 개발용 스크립트).
- 테스트 미러: `tests/exchange/test_fill_convention.py` · `test_execution_input.py` → `tests/data/`, `tests/domain/test_shapes.py`
  → `tests/data/`, `tests/data/test_validation.py` → `tests/data/test_verification.py`.
- characterization 기준선(`check_and_run_envelopes.baseline.json`)은 거절의 `cause.where`에 모듈 경로를 적는다. 세 곳의
  `vqapr/data/validation.py`를 `vqapr/data/verification.py`로 바꿨다 — 경로만, 거절 문구는 한 글자도 그대로다. skill의 보고서
  템플릿 예시 경로 하나(`report-issue-dev`)도 새 경로로.

## 트레이드오프

- `require_identifier`는 공개 이름이 됐다(`domain/identifiers.py`). 두 모듈이 다른 모듈의 비공개 이름을 import하지 않게 하려는
  것이고, 검사와 메시지는 그대로다.
- `ExecutionTable.select_target(horizon=None)`은 호출마다 스캔한다 — 예전 fallback과 같다. run의 경로는 모두 horizon을 넘기므로
  (preflight · 콜백) 이 경로는 테스트와 단발 조회만 탄다.
- 도메인의 `Panel` Protocol은 삭제했다. 그것을 import하는 코드가 없었고, 테스트 한 줄(`isinstance(Panel, type)`)이 그 존재만
  확인했다(설계 §16-11).

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1794 통과 · 5 skip (212 s) |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | campaign 기준선 81 항목과 정확히 같다 (`show_003` 두 항목은 수동 showcase라 둘 다에 없다) |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors |
| `tests/boundaries/test_the_layers_hold.py` | `domain/fill.py`가 층 0 안에서만 import(스캔 경로가 빠진 뒤), `OPEN` 비어 있음 |
| `tests/boundaries/test_physical_reads_pass_one_door.py` | 스캔 검사 커널을 부르는 모듈은 `data/verification.py` 하나 |
