# 2026-09-08 — 아젠다는 아무도 고르지 않은 role을 들고 다닌다

**어떻게 나왔나.** `src/vqapr/domain/agendas.py`가 무슨 코드인지 묻는 질문에서 시작해
`flow/preflight.py` → `flow/frozen.py` → `flow/loop.py`를 따라 읽다 나온 것들이다. 코드를 고치지
않았고, 아래는 전부 이 브랜치(`develop`, `43f59eb0`) 소스에서 확인한 사실이다. **결함 하나
(`A`)와 죽은 무게 둘(`B`·`C`), 모양 문제 둘(`D`·`E`), 탐색 문제 하나(`F`)**로 나눈다.

record `148`이 "아젠다는 등록된 선언이 아니다 — run이 세션과 시각을 말하고 preflight이 파생한다"로
바꾼 뒤, **파생값이 된 타입이 여전히 외부 입력이던 시절의 모양을 그대로 입고 있다**는 게 아래
다섯 개의 공통 뿌리다.

---

## A. DataModel run의 아젠다가 `STRATEGY_CALLBACK`으로 굳고, 그 거짓이 run identity 안에 들어간다

**무게: 이것 하나가 진짜 결함이다.**

`_freeze_datamodel`은 파생 아젠다를 이렇게 굳힌다:

```python
# preflight.py:622
agenda = _freeze_agenda(
    decide, expected_role=OperationRole.STRATEGY_CALLBACK, start=start, end=end
)
```

DataModel에는 콜백이 없다. `flow/loop.py`의 docstring이 그 점을 명시한다 — *"datamodel은 account
없고 execution 없는 strategy처럼 돌아야 해"* (record `148`, 오너). 역할이 다르다는 게 두 run kind를
가르는 유일한 사실인데, 굳은 아젠다는 둘 다 같은 role을 든다.

그리고 이건 표시상의 문제로 끝나지 않는다. `FrozenAgenda.encoded()`가 role을 identity에 접는다:

```python
# frozen.py:88
return (
    self.agenda_role.value,      # <- "STRATEGY_CALLBACK"
    self.timezone,
    [occurrence.local_instant.identity() for occurrence in self.occurrences],
)
```

`FrozenDataModel.identity`(frozen.py:246)가 `agenda.encoded()`를 부르므로, **DataModel run의 신원
해시 안에 그 run이 하지 않는 역할의 이름이 들어 있다.** `encoded()`의 docstring은 무엇을 접고 무엇을
접지 않는지(=id·provenance·occurrence id는 안 접는다) 신중하게 논증하는데, 정작 접는 세 개 중
하나가 DataModel에 대해 참이 아니다.

**어느 쪽이든 결정이 필요하다.** (1) `OperationRole`에 DataModel의 역할을 추가하고 파생 시점에
run kind로 고른다, 또는 (2) 파생 아젠다에서 role을 빼고 — `B`가 말하듯 role은 아젠다 안에서 아무
일도 하지 않으므로 — dispatch 종류는 run kind가 이미 아는 사실로 남긴다. **오너 판정이 필요한
자리**다: (2)는 `encoded()`를 바꾸므로 기존 run identity가 전부 바뀐다.

---

## B. role 우선순위가, 일어날 수 없는 merge를 정렬한다

`agendas.py:35`의 `_ROLE_PRIORITY`와 `operation_role_priority()`는 같은 순간에 겹친 occurrence를
role로 줄 세우기 위해 있고, `OperationOccurrence.sort_key()`(agendas.py:123)의 두 번째 항이다.
그런데 그 tie-break가 닿을 수 있는 입력이 없다:

- 아젠다는 **단일 role**이다 — `__post_init__`이 강제한다: *"every occurrence role must match the
  agenda role"* (agendas.py:156). 그러니 한 아젠다 안에서 두 번째 정렬 항은 상수다.
- run당 아젠다는 **하나**다 — `derived_agenda`(preflight.py:44)의 docstring: *"there is no second
  agenda to build."*
- `merged_occurrences(*agendas)`(frozen.py:95)는 가변 인자인데 **호출부가 하나뿐이고 인자도 하나**다
  (frozen.py:412).
- `VALUATION`·`MONITORING`은 아젠다 role로는 아무 데서도 안 쓰이고, `valuation.py:231`·`364`에서
  recorder의 `stage=` 문자열 라벨로만 살아 있다. 정렬과는 무관하다.

`loop.py`에서 role 우선순위가 실제로 비교되는 유일한 상대는 `DueExecutionEnvelope`의 `-1`
(loop.py:53)이다. 즉 "0이냐 -1이냐"만 의미가 있고, **1과 2는 도달 불가**다.

메모리에 적힌 규칙 그대로다 — *"테스트만 부르는 멤버는 필요성 확인 후 삭제"*. 여기는 테스트조차
부르지 않는다.

---

## C. `provenance`는 계산되고 검증되고 실려 다니는데, 아무도 읽지 않는다

`OperationAgenda.provenance`는 비어 있지 않은 문자열이어야 하고(agendas.py:151),
`provenance_identity`가 그것을 sha256로 접고(agendas.py:188), preflight이 `FrozenAgenda`로
옮기고(preflight.py:113), `FrozenAgenda`가 **짝 존재 규칙까지** 검사한다:

```python
# frozen.py:63,71
if not self.timezone and (self.content_identity or self.provenance_identity):
    raise ValueError("agenda identities require a timezone")
...
if bool(self.content_identity) != bool(self.provenance_identity):
    raise ValueError("agenda identities must be supplied together")
```

**그리고 어느 독자도 그것을 읽지 않는다.** `src/` 전체에서 `provenance_identity`는 위 세 곳(정의·
대입·검증)에만 나오고, record가 남기는 것은 `content_identity`뿐이다(record.py:1739, 1817).
`tests/`·`showcases/`에도 없다. `encoded()`는 provenance를 **일부러 접지 않는다**고 명시한다.

값 자체도 이미 파생이다 — record `148` 이후 provenance는 항상
`f"run {definition.run_id}"`(preflight.py:85)라서, 남은 정보량이 0이다.

즉 **필드 하나 + 해시 하나 + 검증 규칙 두 개가, 소비자가 없는 사실을 지키고 있다.**

---

## D. 파생값인데 외부 입력처럼 방어한다

`_freeze_agenda`가 스스로 이유를 적어 놨다:

```python
# preflight.py:101
# OperationAgenda construction retains and proves every local fold/offset. Calling this
# method additionally makes malformed externally supplied agendas fail before a run exists.
```

**외부 공급 경로가 없다.** `src/` 안에서 `OperationAgenda`를 만드는 곳은 `derived_agenda` 하나뿐이다.
`role` 불일치 검사(preflight.py:97), offset 증거 검사(preflight.py:104), `inclusive_slice`의 두 번째
자르기(이미 issue `069`가 날짜로 미리 잘라놨다, preflight.py:60~78) — 전부 "누군가 이상한 아젠다를
줄 수 있다"를 전제한 층이다.

`A`가 어느 쪽으로 닫히든, **이 방어층이 무엇을 막고 있는지 한 번은 물어야 한다.** 파생값에 대한
불변식이라면 `daily()` 안에 있어야 하고, 거기에는 이미 DST 거부가 그 모양으로 들어 있다.

---

## E. identity 메모는 고친 게 아니라 증상을 눌러 둔 것이다

세 곳이 frozen dataclass를 `object.__setattr__`으로 뚫어 캐시한다 — `OperationOccurrence`
(agendas.py:110), `OperationAgenda`(agendas.py:172, 190), `FrozenRun`/`FrozenDataModel`
(frozen.py:168, 240). 이유는 docstring이 직접 적었다:

> `FrozenRun.identity` re-derives it for every occurrence of every agenda on each access, and a run
> reads that identity about sixteen times per callback, so recomputing made the run quadratic in
> its own length. (agendas.py:83)

**진짜 모양은 "접근할 때마다 다시 계산되는 identity"이지 "캐시가 없다"가 아니다.** identity는
freeze 시점에 한 번 계산해 `FrozenAgenda`가 이미 들고 있는 필드로 넣을 수 있고
(`content_identity`는 실제로 그렇게 들어간다), 그러면 memo도, `object.__setattr__`도, "lazy로 둔
이유"를 설명하는 docstring도 필요 없다. issue `069`의 날짜 선-절단과 record.py의 chunk 누적
(run_state.py:99 주석)이 전부 같은 뿌리 — **파생값을 읽을 때마다 다시 만든다** — 에서 나온 개별
처방이다.

낮은 우선순위다. 지금 코드는 맞고 빠르다. 다만 같은 처방이 네 번 반복됐다는 건 기록해 둔다.

---

## F. 저자가 쓰는 클래스는 파일 이름으로 찾을 수 없다

결함은 아니고 탐색 비용이다. 이 리뷰가 시작된 계기 자체가 그것이었다("datamodel이랑
strategymodel은 어디 정의되어 있어? 왜 안 보이지?").

- `DataModel`(authoring.py:322)과 `StrategyModel`(authoring.py:945)은 1,193줄짜리 `authoring.py`
  안에 있다. one-shape 캠페인이 엔진 쪽 `models/`를 지우고 합친 결과이고, `Model` docstring이 그
  이유(issue `036`: 저자가 쓰는 클래스와 로더가 돌리는 클래스가 달랐다)를 옳게 적고 있다.
- 그런데 **`flow/datamodel.py`라는 이름이 따로 있다.** 거기 있는 것은 `DataModelFlow`·
  `DataModelOutput`·`DataModelPhase` — 저자의 클래스를 *실행하는* 엔진이다. 이름이 가리키는 것과
  파일이 든 것이 다르고, 전략 쪽 대응물은 `flow/callback.py`라 대칭도 없다.
- `domain/values.py`는 `memory.py`와 `enums.py`를 배너 주석(values.py:297, 345) 아래 접어 넣었고,
  `loop.py`는 `events.py`를 접었다(loop.py:19). 접은 것 자체는 record `162`의 결정이지만,
  **`ModelMemory`를 파일 이름으로 찾을 방법은 이제 없다.**
- `vqapr/__init__.py`는 lazy import라 탭 완성에도 안 걸린다.

**제안은 파일 재배치가 아니다** — 그건 이미 캠페인이 한 번 판정했다. 대신 `authoring.py` 상단
docstring이 "저자 표면은 전부 여기, 엔진 쪽 동명 모듈은 실행이다"를 한 문장으로 말하고,
`flow/datamodel.py` 상단이 "이것은 `authoring.DataModel`이 아니다"를 말하면 이 질문은 다시 안 나온다.

---

## 정리

| | 무엇 | 무게 | 다음 |
|---|---|---|---|
| `A` | DataModel 아젠다가 `STRATEGY_CALLBACK`으로 굳고 identity에 접힌다 | **결함** | 오너 판정 — role 추가 vs 아젠다에서 role 제거(identity 깨짐) |
| `B` | role 우선순위가 도달 불가 | 죽은 무게 | `A`와 함께 정리 |
| `C` | `provenance`/`provenance_identity`에 독자가 없다 | 죽은 무게 | 삭제 후보 |
| `D` | 파생값을 외부 입력처럼 방어 | 모양 | `A` 닫을 때 같이 |
| `E` | identity를 접근마다 재계산 → memo 네 곳 | 모양 | 낮음 |
| `F` | 저자 클래스가 파일 이름으로 안 잡힘 | 탐색 | docstring 두 줄 |

`A`~`D`는 한 덩어리다 — 전부 record `148`이 아젠다를 선언에서 파생값으로 바꾸면서 **타입이 옷을 갈아
입지 않은 자리**다. 하나씩 닫으면 네 번 열린다.
