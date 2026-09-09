# 215 — A model's opening memory is an empty mapping

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/089` — 첫 callback에서 `self.memory`가 `None`이라 문서의 예제가 죽는다 |
| **브랜치** | `develop` |
| **앞선 기록** | `214` (두 시계 캠페인 완료) · `139` (frozen initial memory가 로드된 strategy에 닿는다) |

---

## 왜 이 변경이 있는가

`make-strategy`의 `memory-and-payload.md`는 *"Restored before every `decide()`, snapshotted
after"*라 말하고, 예제는 `self.memory.setdefault("sessions", 0)`을 guard 없이 부른다. 그런데 run이
`initial_model_memory`를 선언하지 않으면 frozen layer의 opening memory는 `None`이었고
(`FrozenStrategy.initial_model_memory: ModelMemory = None`, `StrategyEntry`도 같음), 첫 callback은
그 `None`을 restore받아 예제가 `AttributeError`로 죽었다. testbed는 이것을 11개 strategy run 하나와
최소 probe 하나로 재현했고, `vqapr check`는 `ok: true`였다 — preflight는 `save_payload`/`load_payload`
쌍은 증명하지만 memory의 모양은 아무것도 증명하지 않으므로.

산문이 약속한 것과 코드가 준 것이 달랐고, 보고자가 짚은 대로 **작은 쪽은 코드**다: 문서가 dict를
전제하는 이유는 그것이 자연스러운 계약이기 때문이고, `None`은 "아직 snapshot이 없다"는 엔진 내부
사정이 사용자에게 새어 나온 것이다.

## 무엇이 어떻게 바뀌었는가

한 함수, 네 자리.

- `domain/values.py` — `opening_memory(value)`: `normalize_memory` 뒤에 `None`이면 `{}`. 다른
  strict-JSON 값(list, scalar)은 선언한 대로 둔다.
- `project/run.py` — `StrategyEntry`·`DataModelEntry`의 `initial_model_memory` 기본값이
  `Field(default_factory=dict)`, validator가 `opening_memory`. 선언된 `null`도 같은 `{}`로 읽는다:
  "선언 안 함"과 "없다고 선언함"은 하나의 opening state다. `_entry_body`는 `{}`도 `None`처럼 문서에
  쓰지 않는다 — 문서는 원래 빈 memory를 적지 않았다.
- `flow/declaration/frozen.py` — `FrozenStrategy`·`FrozenDataModel` 기본값 `field(default_factory=dict)`,
  `__post_init__`이 `opening_memory`.
- `flow/engine/run_state.py` — `RunStateRepository`가 받은 initial memory에도 `opening_memory`.
  frozen 없이 repository를 직접 seed하는 테스트(`test_time_002`)가 frozen과 같은 첫 state ref를
  얻어야 하므로.

문서: `memory-and-payload.md`가 "첫 callback에서 `{}`"를 한 문단으로 말하고, run 밖에서 직접
만든 인스턴스는 `None`임을 덧붙인다(`inputs()`는 그 인스턴스에서 불리며 memory를 읽지 않는다).
architecture §5.1.1 인접 문장에 한 줄. `docs/releases/0.11.0.md` 시작.

## 대안과 트레이드오프

- **문서만 고치고 예제를 방어적으로 쓴다** (`memory = self.memory or {}`). identity를 건드리지 않아
  migration 비용이 0이다. 기각: 산문의 약속("restored before every decide")이 그대로 거짓으로 남고,
  모든 사용자가 같은 guard를 쓰게 만든다. 보고자도 코드 쪽이 작다고 판정했다.
- **restore 시점에만 `None`을 `{}`로 바꾼다** (frozen 값은 `None` 유지 → identity 불변). 기각:
  frozen이 말하는 opening state와 callback이 받는 값이 달라지고, 첫 snapshot이 `{}`가 되어 record와
  frozen이 어긋난다. 한 값이 한 곳에서 정해지는 쪽을 택했다.

**비용: 모든 run identity가 바뀐다.** `initial_model_memory`는 `FrozenStrategy.identity`와
`FrozenDataModel.identity`에 접혀 들어간다. opening memory를 선언하지 않은 0.10.0 record는
0.11.0이 계산한 identity와 다르고, 같은 run id로 다시 돌리면 `RunRecordConflict`("a run id's
records all belong to one configuration")로 거절된다. 0.10.0이 막 identity를 전부 바꾼 직후라
결정을 소유자에게 물었고, **기본값 `{}` + 0.11 migration 노트**로 승인받았다(2026-09-10).

## 검증

```
.venv/Scripts/python.exe -m pytest tests/project/test_run.py tests/flow/declaration tests/flow/run/test_session_callbacks.py tests/flow/run/test_a_datamodel_is_a_run.py tests/boundaries/test_public.py tests/models/test_agent_first_authoring.py tests/flow/test_acceptance.py -q
  91 passed (첫 실행; 이후 새 테스트 셋 추가)
.venv/Scripts/python.exe -m pytest tests/acceptance/test_time_002.py tests/cli/test_a_datamodel_run_through_the_cli.py tests/characterization tests/flow/run/test_session_callbacks.py -q
  139 passed (rollback 테스트의 `memory is None` 단언을 `== {}`로 고친 뒤)
.venv/Scripts/ruff.exe check src/      All checks passed
.venv/Scripts/python.exe -m pytest tests/ -q     (기본 suite; 결과는 커밋 메시지 시점의 실행)
```

새 테스트:
- `tests/project/test_run.py::test_an_undeclared_opening_memory_is_an_empty_mapping` — entry 두 종류,
  `None` 선언, 기본값 인스턴스가 공유되지 않음.
- `tests/flow/run/test_session_callbacks.py::test_the_documented_memory_example_runs_on_the_first_callback`
  — 문서 예제를 글자 그대로 옮긴 strategy가 두 세션을 돌고 `{"sessions": 2}`를 남긴다.

바뀐 단언 둘: `test_strategy_intent_requires_a_flow_owned_execution_target`의 `memory is None` →
`== {}`(restore된 opening memory); `test_time_002`는 repository 기본값이 같아져 그대로 통과.

## 남은 것

- `vqapr check`는 여전히 memory의 모양을 증명하지 않는다. 이제 증명할 것이 없다 — 첫 callback이
  받는 값이 정해졌으므로 — 하지만 `initial_model_memory`에 mapping이 아닌 값을 선언한 run에서
  `setdefault`를 부르는 strategy는 여전히 502로 죽는다. 그것은 선언한 사람의 것이다.
- 0.11.0 릴리스 노트에 migration 항목 1번으로 적혀 있다.
