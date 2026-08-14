# `agent/skill/` — 설치되는 skill 원본

`vqapr agent install`이 이 디렉터리의 내용을 target의 skill directory로 복사한다
(`agent/targets.py`가 정한 normative path).

## 담아야 하는 것

| 파일 | 역할 |
|---|---|
| `SKILL.md` | required entrypoint. PRD §11.2가 정한 이름 |
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
