# 239 — A callback frames its memory once

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — 0.13.0 stepper의 트레이스(`experiments/exp_238_the_scenario_trace_0_13_0/`)가 보인 중복을 닫는 bounded fix, 기록 `238`의 짝 |
| **이슈** | 없음 |
| **설계 근거** | 기록 `195`: `prepare_model_state`는 memory를 정규화(엄격한 JSON의 분리된 사본)하고 payload와 함께 봉투로 묶어 해시한다 — ref는 오직 거기서만 발급된다. 기록 `221`(root 검증은 콜백 수에 선형): 이미 증명된 ref는 다시 증명하지 않는다 |
| **브랜치** | `develop` (기록 `238` 뒤) |
| **앞선 기록** | `181`(모든 컴포넌트의 memory는 콜백 전에 복원된다), `195`, `221`, `238` |

---

## 왜 이 변경이 있는가

stop-loss run의 트레이스(`10_run_stoploss`, 첫 콜백 #13319 ~ #15085)에서 콜백 하나가 자기 memory를 **다섯 번**
정규화하고 봉투를 **두 번** 해시했다:

| # | 자리 | 하는 일 |
|---|---|---|
| #14668 | `_candidate_callback_state` → `normalize_memory` | 전략이 남긴 memory의 분리된 사본 |
| #14699 | 같은 곳 → `prepare_model_state` → `normalize_memory` | 그 사본을 **다시** 정규화하고 해시해 ref를 얻는다 |
| #14795 · #14826 | `_validate_candidate_payload` → `normalize_memory` ×2 | 살아 있는 전략에 건네는 분리된 사본 둘(round-trip 전후) |
| #14971 | `RunStateRepository.prepare_callback` → `prepare_model_state` → `normalize_memory` | root가 같은 memory와 payload를 **다시** 묶고 해시한다 |

정규화는 값 순회 + 사본, 해시는 json dumps + sha256이다. 콜백당 1 ms 남짓이지만 세션 수에 비례하고, 다섯 중
둘은 같은 입력에 같은 답을 내는 일이다: #14699는 #14668의 결과를 다시 정규화하고, #14971은 #14699가 이미 발급한
ref를 같은 바이트로 다시 발급한다.

## 무엇이 어떻게 바뀌었는가

`CallbackHandler._candidate_callback_state`(`flow/run/callback.py`)가 `PreparedModelState` 하나를 돌려준다:
`prepare_model_state(strategy.memory, payload)` **한 번**이 분리된 사본 · payload · ref를 다 만든다. 그 사본이
`_validate_candidate_payload`에 들어가고(전략에 건네는 두 사본은 그대로다 — 그것이 전략이 root의 memory를
aliasing하지 않게 하는 것이다), 그 ref가 evidence에 들어가고, 그 객체가 `_prepare_callback_publication`을 거쳐
`RunStateRepository.prepare_callback(..., prepared=candidate)`(`flow/engine/run_state.py`)로 간다. root는
`prepared`가 있으면 다시 묶지 않고 그대로 든다 — `prepare_model_state`가 발급한 것이므로 ref는 증명된 것으로
들어간다(기록 `221`의 `_verified`). `prepare_callback(memory, payload)`의 기존 모양은 그대로다(`prepared`는 키워드,
기본 `None`); 테스트와 다른 호출자는 바뀌지 않는다.

콜백당 정규화 5 → 3(묶기 1 + 전략의 사본 2; 복원 때의 사본 2는 별도), 해시 2 → 1. 같은 입력을 같은 함수로 한 번
묶으므로 ref와 record는 바이트 단위로 같다 — showcase digest가 그것을 확인한다(아래).

**바꾸지 않은 것.** `_validate_candidate_payload`의 두 사본과 복원 때의 사본(`load_model_state`): 각각 살아 있는
객체를 root의 값에서 떼어 놓는 일이다. `prepare_model_state` 자체.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/run/test_session_callbacks.py::test_a_callback_frames_its_memory_once` (신규) | Hold 콜백 둘: `prepare_model_state`는 콜백마다 `callback` 모듈에서 1회, `run_state`에서 0회; `normalize_memory` ≤ 5 × 콜백 + 1(seed). 기록 238까지의 트리(`git archive HEAD~1`의 `src`)에서는 같은 테스트가 "4 framings for 2 callbacks"로 실패한다 |
| `tests/flow/test_hot_path_costs.py::test_model_state_verification_is_linear_in_callback_count` (기존) | root 단위의 상한(≤ 4 × 콜백) 그대로 통과 |
| `tests/flow` | 154 passed |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
| `uv run python -m pytest tests/ -q -m ""` (test_all) · `scripts/showcase_record_digest.py --check` | 1,734 passed (172 s, 기록 238과 함께) · 83/83 entries match — ref와 record는 바이트 단위로 같다 |
