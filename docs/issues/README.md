# Issue ledger — 상태 한 줄씩

**작성 2026-09-02 · 갱신 2026-09-02.** 이 디렉터리에 52개 파일이 있고 **44개가 닫혔다.** 닫힌 파일을 옮기지 않는
이유는 `src/`의 docstring 103곳과 `docs/`의 154곳이 이 번호들을 **결정의 근거**로 인용하기
때문이다 — 경로를 바꾸면 그 인용이 전부 끊긴다. 대신 이 파일이 색인이다.

**읽는 법.** 열린 것만 보려면 §1을 읽는다. §2는 닫힌 것들이고, 무엇이 닫았는지만 적는다.
각 파일 안의 `**Status:**` 줄이 여전히 authority이며, 이 표는 그것을 모은 것이다.

> **이 디렉터리는 이슈 목록으로 닫히지 않는다.** 열린 여덟 중 넷(`034`·`035`·`040`·`046`)은
> 서로 다른 다섯 개의 결손이 아니라 아키텍처에 세 개의 명사(**Panel · Surface · Run**)가 없어서
> 생긴 증상이다. 그 설계는 `docs/design/the-panel-the-surface-and-the-run.md`에 있고,
> `docs/vqapr-architecture.md` §17이 그것을 소유자 mental model과 대조한다. **하나씩 닫으면
> 다섯 번 고치고 다섯 번 다시 열린다.**

---

## 1. 열린 것 — 여덟

| # | 제목 | 상태 (2026-09-02 재확인) | 어디로 가는가 |
|---|---|---|---|
| `023` | 하나의 digest가 그 아래에서 바뀔 수 있는 파일을 기술한다 | **절반 열림.** docs 절반은 `fix/023-narrow-the-provenance-promise`가 닫았다. 코드 절반(`show run`의 `matches`/`differs` 읽기)은 HELD — gate가 되면 `009`의 결정을 뒤집는다 | 명사 3 (Run record) |
| `027` | 아무것도 convention을 소리 내어 말하게 하지 않는다 | **REOPENED 2026-08-31 by owner.** `register`가 point-in-time convention을 묻게 해야 한다. `034`와 합쳐진다 | `034`와 함께 |
| `034` | run이 자기가 어떤 execution convention을 썼는지 말하지 못한다 | **열림.** 소유자가 원하고 shape도 제안됐으나 안 만들었다. 이것을 닫았다고 적힌 record는 실제로 닫지 않았다 | 명사 3 (Run record) |
| `035` | 유일한 데이터 accessor가 파일보다 90배 느리다 | **owner-decided, 미구현.** ruling: 검증은 읽기 경로에서 절대 일어나지 않는다(그 절반은 record `119`로 닫혔다). 남은 절반인 columnar accessor는 **레인 C 병합 후 재측정**하기로 미뤄져 있었고, 레인 C는 `df571533`로 병합됐다 — **재측정 차단이 풀렸다** | 명사 1 (Panel). §2.3이 *"panel이 이미 columnar이므로 035는 새 작업이 아니다"*라고 흡수한다 |
| `040` | agenda가 전략 하나만 구동하고 template은 반대로 읽힌다 | **owner-decided(agenda는 공유 가능), 미구현.** 실환경에서 실측 확인됨 — `vqapr-enhanced-index-3` A2가 같은 cadence의 factor 6개에 agenda 6개를 선언하게 만들었다 | 명사 3의 전제조건 |
| `046` | factor book이 callback당 고정 비용을 내고 선언된 입력마다 두 번 왕복한다 | **절반 닫힘.** 후반(왕복 2→1)은 record `120`. **전반(한 스캔이 여러 field) = 레인 D, 열림** — worktree가 아직 만들어지지 않았다 | 읽기 경로 캠페인 레인 D |
| `052` | showcase 9개 중 5개가 안 돌고, 아무것도 그것들을 실행하지 않는다 | **절반 열림.** 다섯 showcase는 다시 돈다 — 둘은 `131`, 셋은 `133`(빠진 config 키 하나, 퇴역한 attribute 이름 둘, 패키지가 빚진 read-through 하나). **gate 절반은 열림** — `pytest`가 `showcases/`를 수집하지 않아 계약이 바뀌면 다시 썩는다 | 캠페인 게이트(“showcase 9개 완주”)는 손으로 잰다 |
| `049` | 패키지 자신의 데이터 가이드를 따르면 614배 느리다 | **ruling은 구현됨**(record `123`), **파일은 번호를 위해 열려 있다.** 남은 것: 레인 D, 그리고 **이 파일이 존재하는 이유인 최종 측정** — 아직 안 됐다 | 캠페인 앵커 |

### 열린 아홉에 없는 것 — 아직 파일이 없는 실환경 발견

`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md`(2026-08-31, FF5+MOM 12 book + residual
2벌을 실제로 만든 세션)가 보고했고 **이 디렉터리에 대응 파일이 없는 것들**. 2026-09-02 평가에서
확인했다.

| 실환경 id | 무엇 | 확인 |
|---|---|---|
| A3 | 여러 항목을 담은 선언 파일의 등록이 **원자적이지 않다** | `declarations.py::_apply`가 섹션마다 `Workspace.create(...).register_*()`를 따로 부르고, 각각이 자기 lock + read-modify-write를 돈다. k번째에서 실패하면 1..k-1은 남고, 등록은 immutable이므로 수정본을 다시 넣을 수 없다. **그 세션에서 가장 비쌌던 항목** |
| A4 | run 기록 **19GB / 12 run**, 끝날 때 한 번에 쓴다 | `vqapr.account`가 valuation마다 보유 종목 전부를 JSONL 한 행씩. 실제로 읽히는 것은 `_ACCOUNT` 행 0.07% |
| A5 | 프레임워크가 **자기가 경고한 tz 함정에 빠지는 포맷으로** 출력을 낸다 | JSONL run 기록을 `read_json_auto`로 읽으면 9시간 밀린 tz-aware 값이 나오고, 그 패널이 등록을 **통과한다** |
| A6 | 큰 run은 `vqapr show run`으로 읽을 수 없다 | 26만~260만 행 JSON이 stdout으로. 문서화된 표면을 우회하게 되고, 그 우회가 A5를 만든다 |
| A7 | 등록이 id는 지키는데 그 id가 가리키는 **파일 내용**은 안 지킨다 | `023`의 이웃이지만 같지 않다 — `023`은 run record의 digest, 이것은 dataset 등록에 digest가 없다는 것 |
| C4 / E1 | 등록 취소가 없고, workspace에 소유권 개념이 없다 | `Workspace.remove()`는 있고(`workspace.py:1042`) 부르는 verb가 없다. 아키텍처 §17.5가 run 삭제에 대해 같은 말을 한다 |
| C5 | `--out /dev/null`이 Windows에서 `nul.py`를 만든다 | papercut |
| B1 | `type()`으로 만든 StrategyModel이 `__module__ == 'abc'`가 되고 거절 메시지가 아무 데도 안 가리킨다 | papercut, 메시지 문제 |

---

## 2. 닫힌 것 — 마흔넷

| # | 닫은 것 |
|---|---|
| `001` | 문서 계약 정렬 (PRD·Architecture) |
| `002` | CLOSED 2026-08-29 |
| `003` | record `035` |
| `004` | CLOSED 2026-08-20 — owner: template은 통과해야 한다 |
| `005` | record `043` |
| `006` | CLOSED 2026-08-21 |
| `007` | SUPERSEDED by `008` |
| `008` | CLOSED 2026-08-28 |
| `009` | CLOSED 2026-08-28 — fingerprint는 gate가 아니라 receipt |
| `010` | record `066` |
| `011` | CLOSED 2026-08-29 — 아홉 항목 전부 |
| `012` | CLOSED 2026-08-29 |
| `013` | CLOSED 2026-08-29 |
| `014` | CLOSED 2026-08-29 |
| `015` | record `087` |
| `016` | record `088` |
| `017` | 양쪽 절반 다 |
| `018` | record `090` |
| `019` | record `089` |
| `020` | `fix/020-krx-is-long-only` |
| `021` | `fix/021-skill-names-public` |
| `022` | record `093` |
| `024` | record `094` |
| `025` | CLOSED |
| `026` | CLOSED |
| `028` | record `097` |
| `029` | record `098` |
| `030` | CLOSED 2026-09-01, 양쪽 항목 |
| `031` | CLOSED 2026-08-31 |
| `032` | CLOSED 2026-09-01 |
| `033` | CLOSED 2026-08-31 — **semantics 버그가 아니라 steering 버그로** 닫혔다. §15-6 / Panel 설계 §7-1이 그 축을 다시 연다 |
| `036` | records `126`·`128`·`130`·`131`·`132`·`133` — 세 역할이 class 하나씩, scaffold 셋이 한 문법, `_internal/`에 bridge 0. "Both are authored the same way"가 서술이 됐다 |
| `037` | record `099` |
| `038` | record `123` |
| `039` | record `102` |
| `041` | record `102` |
| `042` | CLOSED 2026-08-31 |
| `043` | CLOSED 2026-09-01 (record `108`) |
| `044` | CLOSED 2026-09-01 (record `119`) |
| `045` | record `123` |
| `047` | record `129` — 두 connection factory가 하나의 `_configure`를 지난다 |
| `048` | CLOSED 2026-09-01, docs-only |
| `051` | record `130` — contract 블록이 monitoring 관측을 걷는다. 그 전엔 **모든 기록에서 비어 있었다** |
| `050` | CLOSED 2026-09-01 |

---

## 3. 출하된 wheel과 develop이 갈린다

`kwam-enhanced-index/vqapr-final-testbed/KNOWN-ISSUES.md`는 **`0.2.0a2` wheel 기준**으로 열 개를
싣고 있고, 그 목록의 규칙은 *"the list must be exactly the open set"*이다. **2026-09-02 기준으로
그중 넷이 develop에서 이미 닫혔다** — `K-030`(=`030`), `K-032`(=`032`), `K-038`(=`038`),
`K-043`(=`043`).

그 파일 자신의 규칙대로라면 **닫힌 항목이 목록에 남아 있으면 진짜 finding을 억누른다.** 다음
testbed run 전에 wheel을 다시 빌드하고 `KNOWN-ISSUES.md`를 이 디렉터리에서 재생성해야 한다.
