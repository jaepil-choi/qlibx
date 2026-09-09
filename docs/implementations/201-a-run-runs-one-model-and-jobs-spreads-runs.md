# 201 — A run runs one model, and `--jobs` spreads runs

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M1 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §2.3 |
| **브랜치** | `redesign/two-clocks` |
| **뒤집는 것** | record `139` (한 run이 여러 전략) |

---

## 왜 이 변경이 있는가

record `139`는 run 하나가 여러 전략을 담게 만들었다. 근거는 **여러 전략을 비교하려면 같은 얼린
층을 써야 한다**는 것이었다.

**그 근거는 결정성이 이미 보장한다.** 같은 `reads`·`agenda`·execution table을 선언한 두 run은 같은
얼림을 만든다 (PRD §1.2-6: *"같은 frozen input, data, policy에서 판단 순서, state transition,
diagnostic, 결과가 재현된다"*). 층을 공유하는 것은 **최적화이지 의미가 아니었다.**

그리고 그 최적화가 두 가지를 실제로 비쌌다.

1. **병렬성이 run 안에 갇혔다.** `--jobs`가 한 run의 멤버들을 퍼뜨렸으므로, 서로 아무 관계도 없는
   두 run을 병렬로 도는 방법이 없었다.
2. **다른 날 돌린 두 전략을 비교할 수 없었다.** `run_report`가 *"같은 run 안의 전략들"*을
   비교했기 때문이다.

설계 §2.3이 그 위에 세 번째를 얹는다: 프로젝트가 dataset의 그래프이고 run이 그 화살표라면,
**화살표 하나가 여러 결과를 내는 것은 그래프를 하이퍼그래프로 만든다.** 노드 종류를 하나로 두려면
화살표도 하나여야 한다.

---

## 무엇이 어떻게 바뀌었는가

### 선언

```
RunDefinition.strategies: tuple[StrategyEntry, ...]   ->  strategy: StrategyEntry | None
RunDefinition.datamodels: tuple[DataModelEntry, ...]  ->  datamodel: DataModelEntry | None
RunDefinition.members / .strategy(id) / .datamodel(id) / .member(id)  ->  .member (property)
```

**저장된 spelling은 바뀌지 않았다.** `workspace.yaml`과 선언 문서는 여전히
`strategies: {component_id: {...}}`를 쓰고, 그 블록이 **정확히 하나**를 담는다. 이전에 쓰인
워크스페이스는 실제로 둘을 선언하지 않았다면 그대로 읽힌다. 둘이면 `_the_one_member`가 **이름을
대며** 거절한다.

> `a run names exactly one model; ``strategies:`` named 2 (a, b). Register one run per model --`
> `they share nothing a run has to hold them together for, and independent runs parallelise where`
> `a run's members could not`

spelling 자체를 `strategy:`로 바꾸는 것은 M2로 미뤘다 — `writes`가 선언 모양을 어차피 바꾸므로,
마이그레이션을 두 번 하지 않는다.

### 얼린 run

`FrozenRun`도 같은 모양이 됐다. `dispatch_order(layer)`는 그대로다.

### 실행

`orchestration.run()`에서 멤버 루프와 `jobs>1` 분기가 사라졌다. `_run_datamodels`도 같다.
`run()`의 `strategies=`와 `jobs=` 인자가 없어졌다 — 고를 멤버가 없고, 퍼뜨릴 멤버도 없다.

### 병렬성이 옮겨간 자리

```
전   _in_workers(layers, worker, ..., run_id=...)
     worker(project_root, run_id, component_id, store_root, *arguments)

후   in_workers(run_ids, worker, ..., )
     worker(project_root, run_id, store_root, *arguments)
```

**워커는 이미 "레지스터된 run을 다시 얼려서 그중 하나를 돈다"였다.** 멤버가 하나가 되면
`component_id`가 유도되므로, 인자 하나가 빠지는 것만으로 단위가 run이 된다. 풀 자체는 그대로다.

`docs/issues/archive/073`의 규칙 — *"워커의 실패는 `concurrent.futures`가 pickle할 수 있는
것이어야 한다"* — 은 불변이고, 그것이 strategy 워커가 예외 대신 `StrategyOutcome`을 반환하는
이유다.

### CLI

```
vqapr run <id>            envelope 불변
vqapr run <id> <id> ...   envelope 에 runs: {run_id: <envelope>} 가 생긴다
--jobs N                  target 들 사이를 병렬화한다
--strategy                제거.  고를 멤버가 없다
```

한 target을 부르는 호출자는 아무것도 달라지지 않는다.

**한 가지 축소가 있다.** 다중 target 병렬 경로는 strategy run만 워커 풀에 넣고 datamodel run은
순차로 돈다. datamodel 워커는 거절을 **반환하지 않고 raise**하므로(그 자체는 옳다 — `VqaprError`가
pickle되고 순차 경로와 같은 예외를 낸다), 한 run의 거절이 배치 전체를 끝내는 것을 막으려면 그렇게
해야 했다. Python API(`in_workers`)로는 datamodel run도 병렬로 돌고 그 테스트가 있다.

---

## 무엇을 잃었나

`--strategy`로 run의 일부 멤버만 도는 것. 대체는 run을 나누는 것이고, 그러면 `--jobs`가 오히려 더
일반적으로 작동한다.

`test_a_run_holds_several_strategies.py`는 삭제했다 — 그 파일의 주제가 사라진 기능이다.
그 파일이 지키던 것 중 살아 있는 보장(한 거절이 다른 것을 멈추지 않는다, 워커의 거절이 돌아온다)은
`test_a_run_reports_every_strategy.py`가 **run 단위로 다시 쓰여** 계속 지킨다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""     1607 passed
uv run ruff check src/                       All checks passed
uv run python -m pyright                     0 errors
scripts/showcase_record_digest.py --check    81/81 (M0 기준선과 일치)
```

**record digest가 일치한다는 것이 이 변경의 핵심 증거다.** 선언·freeze·실행이 전부 바뀌었는데
**run이 남기는 것은 한 바이트도 달라지지 않았다.** `runs/<run_id>/strategies/<ref>/`의
`strategies/` 층은 단일 항목 디렉터리가 됐을 뿐이고, 평탄화는 별도 결정으로 남겼다.

테스트 26개 파일이 새 모양으로 옮겨졌다. 대부분 기계적(`strategies=(X,)` -> `strategy=X`)이고,
넷은 주제가 "여러 멤버"였으므로 **같은 보장을 run 단위로** 다시 썼다:

| 옮긴 것 | 어디로 |
|---|---|
| 한 전략의 거절이 다른 전략을 멈추지 않는다 | 한 run의 거절이 다른 run을 멈추지 않는다 |
| 두 datamodel이 한 run에서 병렬로 돈다 | 두 datamodel run이 병렬로 돈다 |
| CLI: 실패한 전략 옆에 성공한 전략이 이름을 갖는다 | `vqapr run good bad`의 `runs:` 항목 |
| panel과 rows 읽기가 일치한다 (한 run의 두 멤버) | 두 run의 출력을 비교한다 |

마지막 줄이 특히 이 설계를 확인해 준다 — **두 결과를 비교하는 것이 원래 그래프가 하는 일**이고,
한 run의 두 멤버여야 할 이유가 없었다.

---

## 남긴 흔적

일괄 치환이 `(strategy,) = report.strategies.values()`를 잘못 바꿨다가 테스트가 잡았다.
`RunReport.strategies`는 **run의 멤버가 아니라 리포트의 전략별 섹션**이라 같은 이름의 다른 것이다.
M2 이후 이름 정리에서 이 충돌을 볼 후보로 적어 둔다.
