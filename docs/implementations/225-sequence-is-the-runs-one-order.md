# 225 — `sequence` is the run's one order

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 L1 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **참고** | 네 종류 캠페인 기록 `205`·`209` (`redesign/four-kinds-and-the-journal`) |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `224` (Evidence keeps a summary, not a mark per name) |

---

## 왜 이 변경이 있는가

L1은 참고 브랜치의 기록 `207`과 `205`를 이식하는 단계였다. **`207`은 이식할 것이 없었다** — develop의
기록 `212`가 같은 것(`_advance`: 전이가 바꾸는 필드만 말한다)을 이미 세웠다. 남은 것이 `205`다.

모든 record 행에 `sequence` 열이 있고 이름은 순서를 말하는데, 값은 **recorder 하나의 테이블 하나 안
색인**이었다(`len(staged)`). recorder는 콜백마다 새로 만들어지므로 콜백이 바뀌면 0으로 돌아갔다.
세 occurrence가 각각 200행을 쓰면 0–199가 세 번. 서로 다른 occurrence의 두 행을 그것으로 정렬할 수
없었다. 참고 브랜치의 `209`가 정직하게 적었듯 **어느 소비자도 그것 때문에 틀리고 있지는 않았다** —
`measure.py`는 `account_version`으로 기간을 나누고 그 키는 체결에 대해 충분하다. 고치는 것은 잘못된
답이 아니라 **이름이 거짓인 필드**다. 한 루프 캠페인이 이것을 하는 이유는 L2·L3가 시장 시계의 한 점을
접으면서 "이 run에서 무엇이 몇 번째로 기록됐나"를 한 숫자로 말할 수 있어야 하기 때문이다.

## 무엇이 어떻게 바뀌었는가

- `flow/engine/run_state.py` — `RunStateRepository.next_sequence()`. 기록되는 모든 행이 저장소를
  지나므로 카운터는 여기 하나다. `_fill_rows(sequencer=)`가 체결 행에도 같은 순서를 준다.
- `authoring/records.py` — `InvocationRecorder(sequencer=)`. 주입이지 import가 아니다: authoring(20)은
  run(65)을 볼 수 없다. run 없이 손으로 만든 recorder(저자의 컴포넌트 테스트)는 스스로 센다.
  `sequence`는 이제 append 시점에 민팅되어 열로 스테이징된다(`221`의 열 경로 그대로).
- `flow/run/context.py` — `FlowContext.next_sequence()`; callback·valuation·compliance의 recorder
  셋이 그것을 받는다.

## record가 바뀐다 — 어떻게, 그리고 그것만

`sequence` 열의 값이 바뀐다. 다른 것은 바뀌지 않는다. 증거: showcase 아홉의 record 테이블 46개를
develop `9ce50725`의 산출물과 `sequence`를 빼고 행 단위로 맞대어 **46/46 동일**, `sequence`만 다르다.
digest 기준선을 이 트리에서 다시 썼다(81 entries; show_003은 손으로 도는 showcase라 빠진다). 두 시계 캠페인이 "재기록 없이"를 자랑으로 적었던
것과 달리 이번은 의도된 record 변경이고, 이 기록이 그 이유다.

## 가드 — `tests/flow/test_hot_path_costs.py`

한 저장소의 sequencer를 받은 recorder 둘과 체결 행이 0·1 / 2·3·4 / 5로 이어진다. sequencer 없는
recorder는 0부터 스스로 센다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1648 passed, 4 skipped
showcase digest                         81 entries 재기록, 재실행 81/81
```
