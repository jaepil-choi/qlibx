# 241 — The judgments and the freeze read one set of facts: `RunFacts`

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 문(run) 캠페인, M3·M4 — `docs/design/2026-09-10-one-door-for-a-run.md`, 브랜치 `redesign/one-door-run` |
| **이슈** | 없음 |
| **설계 근거** | 기록 `240`(문 하나), `069`(agenda는 한 번), `077`(답 못 한 판정은 같은 이유로 blocked), `076`(초기 payload는 두 번째 fresh 인스턴스로 증명) |
| **브랜치** | `redesign/one-door-run` |
| **앞선 기록** | `238`, `240` |

---

## 왜 이 변경이 있는가

기록 `240`이 판정과 freeze를 함수 하나 뒤에 두었지만 둘은 아직 각자 사실을 읽었다: agenda 유도 2회, 집행표
binding 2회, horizon 2회, 전략 import 3회(판정 · freeze · 초기 상태 증명), 거래소 2회. `_agenda_once`가
agenda 하나에 대해서만 "한 번 읽고 실패도 같이 전달"의 모양을 하고 있었다(`docs/issues/archive/069`·`077`).

## 무엇이 어떻게 바뀌었는가

`preflight.RunFacts(workspace, definition)` — 사실마다 한 번 읽고 그 값을, **읽지 못했으면 그 예외를** 묻는
모든 쪽에 다시 준다(`_once`). 다섯 사실: `agenda()` · `execution_table()` · `horizon()` ·
`component(id, loader)` · `exchange()`. `verify_run`이 하나를 만들어 `judgments(..., facts)`와
`preflight_run(..., facts)`에 넘긴다; 둘 다 `facts` 없이 불리면 스스로 하나를 만든다(테스트와 기존 호출자
그대로).

- judge들은 `facts`를 받는다: 집행 순서 판정은 `facts.agenda()·execution_table()·horizon()`, 멤버 dataset
  판정은 `facts.component(id, loader)`, 비중 판정은 `facts.exchange()`. `_agenda_once` 삭제.
- freeze는 같은 사실을 쓴다: `preflight_run`이 `facts.agenda()·exchange()·execution_table()·horizon()`,
  `_freeze_strategy`/`_freeze_datamodel`이 `facts.component(...)`. kind 검사(`ValueError "registered as X, not
  as a strategy"`)는 사실을 묻기 **전에** 그대로 남아 있어 그 거절문은 바뀌지 않는다.
- `_validate_initial_model_state`의 두 번째 fresh 인스턴스 load는 남는다 — 그것이 `076`의 증명이다.

같은 예외 객체가 판정 쪽(blocked의 cause)과 freeze 쪽(거절)에 두 번 raise된다. `check`는 판정의 blocked를
그 자리에서 dict로 만들고 freeze의 거절은 `failures`로만 그리므로 봉투는 같다(특성화 baseline).

**바꾸지 않은 것.** `check` 봉투의 두 wart(기록 240 참조). run 시작 뒤의 전략 재import와 horizon 재스캔
(`RunResources`, 설계 §5).

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/declaration/test_preflight.py::test_one_door_reads_each_fact_of_a_run_once` (신규) | `verify_run` 한 번에 `derived_agenda` 1 · `bound_execution_table` 1 · `bound_execution_horizon` 1 · 집행표 스캔 1 · 전략 load 2(판정+freeze 1, 초기 상태 증명 1) · 거래소 1 · 규칙 1 |
| `tests/characterization/test_check_and_run_envelopes_hold.py` | 봉투 8개 바이트 단위로 같음 |
| `tests/cli/test_check.py`(judge 단위 테스트 4곳은 `RunFacts`를 넘기도록 수정) · `tests/flow/declaration` · `tests/cli/test_a_datamodel_run_through_the_cli.py` · `tests/characterization` | 150 passed, 1 skipped |
| `uv run python -m pytest tests/ -q` (fast) | 1,709 passed, 1 skipped |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
