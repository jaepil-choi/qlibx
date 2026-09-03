# 진단 — 무엇이 어떻게 잘못되어 있는가

**이 디렉터리는 관측만 담는다.** 무엇을 할 것인가는 `docs/refactoring/`에 있고, 무엇을 했는가는
`docs/implementations/`에, 무엇이 열려 있는가는 `docs/issues/README.md`에 있다. 진단이 계획과
같은 파일에 살면 계획이 바뀔 때마다 관측이 다시 쓰이고, 그러면 다음 사람이 **무엇이 실제로
측정되었는지** 알 수 없게 된다.

| | |
|---|---|
| **마지막 갱신** | 2026-09-03 |
| **현행 진단** | [`2026-09-02-what-the-tree-owes-the-mental-model.md`](2026-09-02-what-the-tree-owes-the-mental-model.md) — **§0의 표와 §4의 순서는 전부 집행됐다** (아래) |
| **현행 계획** | [`../refactoring/2026-09-03-the-deletion-campaign.md`](../refactoring/2026-09-03-the-deletion-campaign.md) — 053 → 054 → 두 섹션 퇴역 → pydantic이 codec 대체 → 기록 parquet → `SimulationFlow` 분할 → DataModel = flow 하나. 수렴 캠페인(09-02)은 `d212bceb`에서 Step 0–7 완료 |
| **기준 커밋** | `develop @ v0.3.0` — 1327 passed (fast 1314 + slow 13), ruff clean, showcase 9/9 |

> **2026-09-03.** 아래 §0이 그린 "없는 명사 셋"은 records `133`(Surface) · `137`(Panel) · `139`(Run)로
> 들어왔고, "실환경 결함 다섯"은 `134`(원자적 등록) · `135`(흘려 쓰기, tz 안전한 포맷) · `139`(등록
> digest) · `129`(unused deps)가 닫았다. `049`의 최종 측정은 `experiments/exp_049_the_measurement/`가
> 잰다 (rows 372.57s · expr 5.04s · wide 2.46s, anti-join 0). 그 측정이 새로 낸 관측 둘은
> `docs/issues/053`·`054`다. §0 이하는 **2026-09-02의 관측**으로 남긴다 — 무엇이 측정되었는지의 기록이지
> 할 일 목록이 아니다.

---

## 0. 한 장 — 오늘의 진단

**척추는 건강하다.** PIT 경계, Account single-writer, `intended ≠ requested ≠ dealt ≠ committed`
네 단계, exact-rational optimizer, frozen run identity. 세 번의 독립 감사가 모두 같은 결론을
냈고, 어떤 계획도 여기를 건드리지 않는다.

**문제는 전부 척추 바깥에 있고, 세 개의 없는 명사와 다섯 개의 실환경 결함으로 갈린다.**

```
없는 명사 셋 (docs/design/the-panel-the-surface-and-the-run.md)
├─ Surface  저자 표면이 둘이다 ─────────────  036 (절반 구현) · R5 · R6 · G011
├─ Panel    선언과 창 사이에 표가 없다 ─────  049 · 035 · 046 · §17.1.x · §17.9/10
└─ Run      한 단어가 세 가지 일을 한다 ────  034 · 040 · 023p · §17.3~17.6

세 명사가 덮지 않는 실환경 결함 다섯 (이슈 파일 없음)
├─ 선언 파일 등록이 원자적이지 않다 ────────  🔴 복구 경로가 워크스페이스 전체 삭제
├─ run 기록이 메모리에 쌓였다가 끝에 쓰인다 ─  🔴 19GB/12run, 죽으면 전부 없음
├─ 출력 포맷이 자기가 경고한 tz 함정에 빠진다  🔴 조용한 look-ahead
├─ 등록이 id는 지키고 바이트는 안 지킨다 ───  🟠
└─ 안 쓰이는 runtime dependency 넷 ─────────  🟠 cvxpy·pandas·pydantic·pytz
```

**그리고 이 평가가 새로 발견한 구조적 결함은 없다.** 진단은 세 문서가 이미 옳게 했고, 소유자
ruling도 이미 나 있다. 없는 것은 **착수**다 — 그 간격이 현행 진단 §0의 표다.

---

## 1. 살아 있는 진단

| 문서 | 무엇을 쟀나 | 상태 |
|---|---|---|
| [`2026-09-02-what-the-tree-owes-the-mental-model.md`](2026-09-02-what-the-tree-owes-the-mental-model.md) | 결정과 트리 사이의 간격, 실환경 결함 다섯, gjc ultragoal이 blocked로 남긴 것 | **현행** |
| [`2026-08-31-vqapr-structural-refactoring.md`](2026-08-31-vqapr-structural-refactoring.md) | 141 모듈 전수, S1–S8 구조 smell과 C1–C4 correctness | **부분 유효** — S2·S4·S5·S8과 C1·C2·C3은 닫혔다. S1(protocol 둘)·S3(god module)·S6은 열려 있다. §2의 목표 구조는 **record `104`가 뒤집었다**(아래 §3) |
| [`2026-08-31-post-step-07-review.md`](2026-08-31-post-step-07-review.md) | Step 0–7 실행 후 재감사, R1–R10 | **부분 유효** — R1·R2·R3·R4·R7·R8이 닫혔다. **R5(loader가 authoring을 하나만 받는다)·R6(scaffold 셋이 표면 둘을 emit)·R9·R10은 열려 있고**, R5/R6은 현행 진단 §2.1이 재확인했다 |

**세 문서를 다 읽을 필요는 없다.** 현행 진단이 앞의 둘에서 아직 참인 것을 인용하고, 아닌 것을
명시한다. 앞의 둘은 그 인용의 **원 측정**으로 남는다.

## 2. 보관

`archive/`는 **provenance이지 작업 목록이 아니다.** 각 파일 맨 위 배너가 오늘 확인한
resolved/still-live를 항목별로 적고, 재검증하지 않은 항목은 그렇다고 적는다.

| 문서 | 왜 보관인가 |
|---|---|
| [`archive/2026-08-18-vqapr-review.md`](archive/2026-08-18-vqapr-review.md) | 130 modules / 11,959 lines / 334 tests 기준. 오늘 트리는 30,260 lines / 1,292 tests다. **still live: OS-2 · RF-1 · RF-2** |
| [`archive/2026-08-19-vqapr-performance.md`](archive/2026-08-19-vqapr-performance.md) | 읽기 경로를 그 뒤로 두 번 다시 썼다(records `104`–`118`, `119`–`128`). 이 파일의 논지 전체가 `docs/issues/049`의 숫자 하나가 되었다 |

## 3. 뒤집힌 진단 — 읽는 사람이 반드시 알아야 할 하나

**`2026-08-31-vqapr-structural-refactoring.md` §2의 목표 구조는 무효다.** 그 문서는
*"`public.py`는 사라지고 `project.py`가 유일 facade"*를 목표로 그렸다. `docs/implementations/
104-which-facade-survives.md`가 PEP 669 line tracer로 그것을 뒤집었다 — 완주하는 CLI journey에서
`project.py` 619줄 중 **실행 0줄**, `vqapr.public`은 shipped 경로 전부에 있다. record `124`가
반대편(13 modules / 4,001 lines)을 삭제했다.

**같은 뒤집힘이 `gjc-handoff/`의 작업 순서와 `docs/design/agent-first-surface.md`의 "The G008
admission conditions" 절에도 걸려 있다.** 현행 진단 §8이 그 경위를 담고, 두 문서를 고치는 것이
계획의 Step 0에 있다.

**교훈은 방법론이다:** 그 오류를 잡은 것은 코드 읽기가 아니라 **실제 제품 여정 위의 tracer**였다.
표면에 대한 진단은 측정으로 갱신하고, 읽기로 갱신하지 않는다.

## 4. 여기 없는 것

- **testbed 발견의 원본**은 소비자 repo에 있다 — `kwam-enhanced-index/vqapr-enhanced-index-3/
  VQAPR-ISSUES.md`, `.../vqapr-final-testbed/{FINDINGS,KNOWN-ISSUES}.md`,
  `kaist-thesis/vqapr-testbed/FRICTION*.md`. 현행 진단 §3과 §6이 그중 프레임워크에 귀속되는 것을
  옮겨 적는다. **testbed는 설치본을 상대로 도는 독립 프로젝트이므로 그 파일들을 이 repo로
  옮기지 않는다.**
- **열린 이슈 목록**은 `docs/issues/README.md`다. 이 디렉터리는 이슈를 세지 않고 원인을 잰다.
- **소유자 mental model과의 대조**는 `docs/vqapr-architecture.md` §17이다. 진단이 아니라 계약
  대조표이므로 아키텍처 문서에 남는다.
