# 242 — The run takes what the verification loaded and read: `RunResources`

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 문(run) 캠페인의 후속 — 설계 §5 "범위 밖"으로 남겼던 것. 브랜치 `redesign/run-resources` |
| **이슈** | 없음 |
| **설계 근거** | 기록 `240`·`241`(문 하나 · 사실 하나), `162`(horizon은 run당 한 번), `076`(초기 payload는 두 번째 fresh 인스턴스로 증명 — 그대로) |
| **브랜치** | `redesign/run-resources` (develop 0.14.0 위) |
| **앞선 기록** | `240`, `241` |

---

## 왜 이 변경이 있는가

기록 241 뒤에도 `vqapr run`은 검증이 끝난 직후 전략 · 거래소 · 규칙을 **다시 import**하고(`_run_strategy`의
`load_*` 셋), 첫 의도서가 받아들여질 때 집행표를 **다시 스캔**해 horizon을 만들었다(`CallbackHandler.execution_horizon`,
트레이스 `08_run_factor` #7639 · #7688 · #8272). 이유는 구조다: `FrozenRun`은 `run.json`에 적히는 record 값이라 살아
있는 인스턴스를 실을 수 없고, 검증이 load한 것은 함수 밖으로 나오지 않았다.

## 무엇이 어떻게 바뀌었는가

- `verify.RunResources(run_identity, strategy, datamodel, exchange, rules, horizon)`: 검증의 `RunFacts`가 이미 들고
  있는 인스턴스와 horizon을 담는 값. `RunResources.of(facts, frozen)`은 아무것도 새로 읽지 않는다(전부 memo hit).
  `RunVerdict.resources`에 실리고 `require_ready() -> (FrozenRun, RunResources)`로 꺼낸다.
- `_freeze_strategy`가 규칙도 `facts.component(name, load_compliance)`로 load한다 — 검증이 든 인스턴스가 run이 쓰는
  인스턴스가 되도록.
- `orchestration.run(..., resources=None)` → `_run_strategy`/`_run_datamodel(..., resources)`: 있으면 그 인스턴스를,
  없으면(FrozenRun만 든 Python 호출자) 전처럼 load한다. `run_identity != frozen.identity`면 `ValueError`로 거절.
  `strategy_loop(..., horizon=)`이 `FlowContext.horizon`을 미리 채운다 — 없으면 기록 `162`대로 첫 의도서에서 한 번
  읽는다.
- `cli/run._run_one`과 두 `--jobs` worker가 `verify_run(...).require_ready()`로 frozen과 resources를 함께 받아 넘긴다.
- run의 `as_loaded` 영수증(실제로 load된 바이트의 fingerprint)은 그대로 디스크에서 다시 잰다 — 같은 프로세스에서
  방금 load한 것이므로 뜻이 같다.

**바꾸지 않은 것.** `_validate_initial_model_state`의 두 번째 fresh 인스턴스(`076`). `public.preflight_run` +
`public.run(frozen)` 조합(스스로 load한다). record 모양 · 봉투 · 코드.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/declaration/test_preflight.py::test_the_run_takes_what_the_verification_loaded_and_read` (신규) | verdict의 resources가 전략 · 거래소 · 규칙 1 · horizon(스캔한 것과 동일)을 들고, `execute_run(resources=)` 동안 `_load` 0회 · `candidate_instants` 0회; 다른 run의 resources는 `ValueError` |
| `tests/characterization` · `tests/cli/test_check.py` · `tests/flow/declaration` · `tests/cli/test_a_datamodel_run_through_the_cli.py` · `tests/cli/test_run_makes_the_judgments_check_makes.py` · `tests/flow/test_run_freezes_its_record.py` | 163 passed, 1 skipped |
| `uv run python -m pytest tests/ -q` (fast) | 1,710 passed, 1 skipped |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
| stamped 트리(0.14.1): `test_all` · showcase digest · `release_check` | 1,739 passed, 1 skipped · 83/83 entries match · every shipped skill file recorded |
