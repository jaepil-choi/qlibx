# `agent/skill/` — 설치되는 skill 원본

`vqapr skill install`이 이 디렉터리의 `SKILL.md`를 프로젝트의 skill directory로 복사한다.
설치 경로는 `.agents/skills/vqapr/`이고, `--target claude|both`면 `.claude/skills/vqapr-skill/`에
본문을 가리키는 thin adapter를 추가로 놓는다. 루트는 가장 가까운 `.git` 조상이며 `--into`로
덮어쓴다.

이 README는 **설치되지 않는다**. 여기를 유지보수하는 사람에게 하는 말이지 skill을 읽는 agent에게
하는 말이 아니고, 설치본에 섞이면 agent가 자기 대상이 아닌 문서를 권위로 읽는다.

## 현재 담고 있는 것

| 파일 | 역할 | 상태 |
|---|---|---|
| `SKILL.md` | required entrypoint. PRD §11.2가 정한 이름 | 있음 |

## 아직 없는 것

아래는 계획이지 현재 동작이 아니다. **없는 것을 현재형으로 쓰지 않는다** — 그것이 FRICTION
F-001의 실제 원인이었다. 문서가 현재형으로 서술한 명령을 찾다가 없다는 것을 알아내는 비용은
읽는 사람마다 똑같이 다시 든다.

| 파일 | 역할 |
|---|---|
| `references/` | availability 유도 규칙 후보, calendar 유도 규칙 후보, discouraged 준비 방식 |
| `examples/` | 최소 등록 예시, 최소 run 예시 |

## skill이 담당하는 것

package는 deterministic하게 판정만 하고, **대화는 전부 여기가 담당한다**(PRD §2.6).

- **등록 이전부터 개입한다.** error 이후가 아니다. `DATE`가 관측일인지 공개 시각인지 묻고,
  look-ahead 위험을 설명하고, 후보를 제시한다(`UC-AGENT-001`).
- **package가 원리적으로 검증할 수 없는 것을 경고한다.** 이동평균·누적합·순위처럼 등록
  query에 쓰면 미래를 반영할 수 있는 패턴, stale price로 읽힐 컬럼 선택(`UC-AGENT-002`).
- **데이터가 증명하는 것과 이름으로만 아는 것을 구분한다.**
- package error를 해석해 **복수의** 해결 경로를 만들고 각각의 가정과 trade-off를 설명한다.
  경제적 의미나 authority를 바꾸는 선택은 **user가 판단하게 한다.**

## skill이 하지 않는 것

- package validation을 우회하지 않는다.
- missing semantics를 추측하지 않는다.
- 근거가 확인되기 전에 binding을 확정하지 않는다.
