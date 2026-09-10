# 228 — One member runner, one facts block

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 L4 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `227` (One loop walks both kinds of run) |

---

## 왜 이 변경이 있는가

`flow/orchestration.py`의 `_run_strategy`(175줄)와 `_run_datamodel`(75줄)이 같은 뼈대를 각자 썼다:
`_FrozenCatalog` → `ScanSession` → `DuckDbObservationStore` → record writer open → 루프 → freeze →
실패하면 writer release → `session.close()` → record 되읽기. 그중 "죽은 멤버가 record의 lock을 쥐고
있지 않게 release한다"는 두 곳이 같이 옳아야 하는 불변식이었고, `ModelWindow`를 만드는 lambda는
세 곳에 같은 여섯 줄로 있었다. `flow/freeze.py`의 두 freeze도 `component`·`agenda` 블록을 글자
그대로 두 번 적었다.

`227`이 루프를 하나로 만든 뒤라 **조립도 하나**가 자연스럽다. 루프가 "부품 + 시장 시계"로 갈렸듯
조립은 "멤버가 공유하는 자원 + 멤버의 몸통"으로 갈린다.

## 무엇이 어떻게 바뀌었는가

- `orchestration.py::_run_member(frozen, *, record_ref, member_kind, store, replace_record, body,
  read_record)` — 세션·store·writer의 수명과 record 되읽기. `body(observation_store, session, writer)`가
  멤버의 몸통이다. **로드와 drift 검사는 `body` 밖, 앞에 있다** — drift된 컴포넌트는 record 디렉터리를
  만들지 않는다는 원래의 순서를 지키기 위해서다.
- `_run_datamodel`·`_run_strategy` — 각자의 로드·검사 뒤에 `body`를 정의하고 `_run_member`에 넘긴다.
  몸통의 내용은 그대로다(주석까지). 바뀐 것은 뼈대가 한 번 쓰였다는 것뿐이다.
- `_window_factory(frozen, observation_store, *, allowed_requirements, consumer_id)` — 세 lambda가
  하나의 팩토리로. 전략 창(소비자 = 전략), 규칙 창(소비자 없음: 규칙마다 `for_consumer`), datamodel
  창.
- `freeze.py::_component_block`·`_agenda_block` — 두 record가 같은 모양으로 적는 두 블록.

record는 바뀌지 않는다: 같은 필드, 같은 값. digest가 지킨다.

**한 번 틀렸다.** 첫 판은 `record_ref=layer.record_ref`를 무조건 평가했는데, store 없이 도는 run(in-process
호출, 컴포넌트가 stand-in인 테스트)은 fingerprint가 없어 `record_ref`를 만들 수 없다. 전에는 writer를
만들 때만 닿았던 것이다. `record_ref`는 `Callable[[], str]`로 받아 store가 있을 때만 묻는다 —
`tests/boundaries/test_public.py`가 잡았고, 게이트의 요약 한 줄만 읽고 커밋했던 것이 실수였다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1648 passed, 4 skipped
showcase digest                         81/81
```
