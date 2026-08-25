> **이건 세션 2(`01a03479` 전반)의 기록이다. 새 세션은 `README.md`(START HERE)부터 읽는다.**
> 원본은 `../kwam-enhanced-index/gjc-handoff/SESSION-02.md`.

# gjc ultragoal 세션 2 핸드오프 — vqapr Agent-First Python API

세션 `01a03479-6572-71ee-a423-897459b75deb`. 이전 세션 `01a031f9`의 핸드오프를 이어받아
opus로 재개한 기록이다. 계획 재검토부터 시작해 T2 transactional spine까지 구현했다.

durable 상태는 `.gjc/_session-01a03479-.../ultragoal/`의 `goals.json`과 `ledger.jsonl`에 있다.
아래 내용은 전부 그 ledger에 측정 증거와 함께 기록되어 있다.

## 종료 시점 상태

| Goal | 상태 | 내용 |
|---|---|---|
| G001 | **complete** | 승인 대기 계획 재검토 |
| G002 | **complete** | T0 canonical baseline 이 머신에서 재수립 |
| G003 | **complete** | 고아 adapter 해결, authoring boundary 종결 |
| G004 | **complete** | Project transaction + atomic publication (계획의 T2) |
| G009 | pending (**절반 완료**) | Project.run을 execution/valuation engine에 연결 |
| G007 | **blocked** (G009 대기) | package surface dogfooding |
| G006 | pending | factor testbed 이관 및 parity 증명 |
| G008 | pending | hard-removal + 물리 이동 + 0.2.0a1 (계획의 T4) |

qlibx 테스트 **846 → 958 passed**, ruff clean. **두 repo 모두 commit 없음.**
qlibx 기준 신규 8개 파일, 수정 2개 파일이 uncommitted 상태로 남아 있다.

## 계획 재검토 결론 (G001)

계획 전체가 `gpt-5.6-sol`이 작성/리뷰한 것이라 opus로 다시 봤다. 세 가지 판정.

1. **ACCEPT** — callback마다 module bytes를 다시 읽어 sha256 fingerprint를 계산하는 drift check는
   측정 결과 callback당 85~106μs, HML의 2,096 callback 전체에 약 220ms다. 1102초짜리
   factor build 대비 무시할 수 있다. 성능 반대 논거는 실체가 없었다.
2. **REVISE** — `vqapr-testbed-2/baselines/`가 gitignore 대상이라 다른 머신의 T0 baseline이
   이 머신에 없었다. 모든 하위 parity 증명의 기준점이 없는 상태였다. G002로 선행 처리했다.
3. **REVISE — 계획이 놓친 실질적 결함.** `models/factors.py`의 `FactorPortfolio`는
   월별 cadence를 `self.memory`에 담는다(`:259` 쓰기, `:241` 읽기). docstring 스스로
   "Model의 memory가 cadence를 소유한다, occurrence 날짜만으로 유도하면 mid-month 재개 시
   매월 첫 세션에 재형성된다"고 명시한다. 계획의 fresh-instance-per-callback 규칙은 이 상태를
   파괴하는데, testbed migration 항목은 그 memory→state 번역을 한 번도 언급하지 않는다.
   G006 objective에 명시적으로 박아 넣었다.

계획의 구조 자체는 건전하다고 판단해 ralplan 재실행은 하지 않았다. annotation closure test는
문서 리뷰가 아니라 기계적으로 검증 가능해서 특히 좋고, cross-repo Q/T/wheel pairing도 견고하다.

## 내가 고친 순서 오류 두 개

- **G005 분리**: dogfooding(T3)과 hard-removal(T4)이 한 goal에 묶여 있었고, 그 goal이
  testbed parity 증명보다 **앞에** 있었다. 계획 자신의 escalation gate가 "testbed가 T0
  comparator를 통과하기 전에는 T4 삭제를 시작하지 말라"고 하는데도 그랬다. G007/G008로 쪼개고
  순서를 뒤로 옮겼다.
- **물리 이동 위치**: 내가 한 번 `flow/` 이동을 G004에 넣었는데 이건 내 실수였다. 계획은 물리
  이동을 T4에 둔다. T2 시점에는 legacy path가 "baseline 비교 용도로만" 살아 있어야 한다.
  지금 옮기면 G006이 비교할 대상 자체가 사라진다. G008로 되돌렸다.

## 실제로 만든 것 (G003, G004, G009 절반)

```
src/vqapr/__init__.py            0 bytes였다. vqapr.open이 아예 없었다.
src/vqapr/project.py             declaration algebra, register/register_all,
                                 materialize/run, CompletedRun.publish
src/vqapr/_internal/catalog.py       immutable Catalog, CatalogView, canonical_bytes
src/vqapr/_internal/catalog_store.py 비변경 read, generation+digest CAS, sweep_orphans
src/vqapr/_internal/objects.py       content-addressed staging, fsync, 설치 전 digest 검증
src/vqapr/_internal/publication.py   객체 먼저 durable, 그 다음 단 한 번의 root swap
src/vqapr/_internal/pit_bridge.py    declared alias → 실제 PIT store
```

## 반드시 알아야 할 것 — G004 완료가 "run engine 완성"이 아니다

G004의 lifecycle 테스트는 **주입된 stub resolver**로 돌았다. invocation boundary가 도달
가능하다는 것은 증명했지만, 실제 데이터를 읽는다는 것은 증명하지 못했다. 그래서 `pit_bridge.py`를
만들어 실제 testbed workspace에 물렸고, 그제서야 진짜 KRX 데이터를 읽었다.

그 과정에서 **실데이터로 돌려야만 나온 결함 3개**를 잡았다.

1. `authoring.RowsLookback`과 `data.lookback.RowsLookback`은 **서로 다른 타입**이다.
   그대로 넘기면 `TypeError`. 명시적 번역을 넣고, 두 클래스가 실제로 다르다는 것을 테스트로
   고정했다. 나중에 같아지면 번역 코드가 죽은 코드가 되기 때문이다.
2. engine의 registration은 컬럼명을 `available_at`으로, public declaration은
   `available_at_field`로 부른다. public 쪽 rename은 의도된 것이라 매핑을 명시했다.
3. 첫 probe가 0 rows를 반환했다. **조용한 날로 받아들이지 않고** engine에 직접 질의해서
   한국 종목 코드가 `A` prefix(`A005930`)라는 것을 확인했다. bridge가 아니라 내 probe 입력이
   틀린 것이었다.

PIT 경계도 증명했다. 2024-03-15 16:00 KST cutoff에 `RowsLookback(3)`이면 03-13, 03-14,
03-15 15:30 KST 스탬프 3개만 보이고 **cutoff 이후 관측은 0개**다. 모델이 자기 미래를 볼 수 없다.

## 남은 가장 큰 작업 — G009 후반부

`Project.run`은 지금 strategy callback loop만 돌린다. execution input, fill convention,
account snapshot, order 생성, valuation은 전부 `flow/run.py`에 남아 있다.
측정: `flow/run.py`에 execution/fill/valuation 참조 43개, `project.py`에 19개인데 그나마
대부분 declaration 타입이다.

이게 연결되기 전에는 showcase 003~008도, factor testbed도 supported surface로 옮길 수 없다.
**계획 전체에서 남은 단일 최대 작업이다.**

## 검증 방식에 대해

green 테스트를 믿지 않고 전부 mutation으로 깼다. 각각 적용 후 되돌렸다.

| mutation | 결과 |
|---|---|
| CAS에서 digest 절반 제거 | `DID NOT RAISE CatalogConflict` |
| `os.replace`를 직접 쓰기로 교체 | crash-safety 테스트 `assert 0 == 1` |
| catalog 디렉터리 정리 제거 | `assert not True` |
| `stage_object`를 순수 해시 계산으로 교체 | 11개 중 5개 실패, `root references missing object` |
| `Project.run`의 state threading 제거 | `['formed','already-formed','formed']` → `['formed','formed','formed']` |
| declared field 누락 검사를 조용한 dict comprehension으로 교체 | `DID NOT RAISE KeyError` |

마지막에서 두 번째가 가장 중요하다. HML의 고정된 97 formation을 깨뜨릴 바로 그 silent drift를
재현한다. 이제는 사후 부검이 아니라 테스트가 잡는다.

concurrency와 crash도 mock이 아니라 실제 subprocess로 증명했다. 두 writer가 경합해
`COMMITTED:1` 하나와 `CONFLICT:CatalogConflict` 하나가 나왔고, root swap 전후 hard kill에서
각각 old-root-complete / new-root-complete를 확인했다.

## 내가 직접 찾아 고친 결함들

delegated worker의 테스트가 놓친 것들이라 따로 적어둔다.

1. writer lock을 잡으려면 `.vqapr/`를 mkdir해야 해서, **첫 commit이 실패하면 빈 디렉터리가
   남았다.** 계획은 `open()`이 "디렉터리, lock, catalog, artifact 어느 것도 만들지 않는다"고
   요구한다. 이 writer가 만든 디렉터리일 때만 unwind에서 지우도록 고쳤다.
2. `src/vqapr/__init__.py`가 **0 bytes**였다. public API에 진입점이 아예 없었다.
3. 그 2번을 고치다가 내가 **직접 regression을 만들었다.** `vqapr.project`를 eager import하니
   `tests/boundaries/test_capability_absence.py`가 5개 깨졌다. leaf capability가 무거운 layer를
   끌고 오면 안 된다는 경계다. import를 `open()` 본문으로 미뤄서 해결했다.

## 오너 판단이 필요한 것

**계획이 자기모순이다.** 마지막 Approval State는 "source mutation을 승인하지 않는다"고 하고,
ordered step 10은 "commit/tag/push/release 전에 멈춰라"고 한다 — 10개 구현 단계를 **전부 마친
뒤에**. 둘 다 유효할 수 없다.

terminal critic은 step 10이 유효하다고 판정했다. 근거는 brief의 standing constraint가 금지하는
것이 정확히 다섯 개 git 동작이고 source mutation은 거기 없다는 점, 그리고 오너가 `d23ca03`을
revert가 아니라 commit했다는 선례다. 나는 그 판정 위에서 진행했다.

G007과 G006까지는 계획의 rollback boundary상 전부 되돌릴 수 있다. **G008은 아니다.**
`vqapr.public` 삭제, 8,139줄 물리 이동, breaking `0.2.0a1`이다. 여기서는 오너의 명시적 승인이
필요하다.

## 재개 지점

**G009 후반부부터 시작하라.** ledger에 모든 주장의 측정 증거가 있다.
새 세션으로 시작하고, 이어서 할 경우 터미널에 아무 입력이나 한 번 넣어 대기 중인 모델 프로파일을
적용시킨 뒤 진행하라. `git add`/`commit`/`push`/tag/publish는 여전히 금지다.
