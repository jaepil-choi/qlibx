# `agent/skills/` — 설치되는 skill 집합의 원본

`vqapr skill install`이 이 디렉터리의 **각 하위 디렉터리 하나를 skill 하나로** 프로젝트에
복사한다. 설치 경로는 두 target 모두 `<target>/skills/vqapr-<skill-name>/`이다.

| target | 경로 |
|---|---|
| Codex | `.agents/skills/vqapr-<skill-name>/` |
| Claude Code | `.claude/skills/vqapr-<skill-name>/` |

**두 target은 같은 bytes를 받는다**(PRD §11.2). 예전에는 `.claude/` 쪽에 본문을 가리키는 thin
adapter를 놓았고 이유는 "복사본이 두 개가 되는 순간 하나는 반드시 stale해진다"였다. 그 논증은
드리프트를 탐지할 방법이 없을 때 맞았다 — 지금은 `agent/skillset.py`의 판정이 target별·파일별로
어긋난 사본의 이름을 대므로 막을 이유가 없고, 반대로 adapter는 읽는 쪽에 한 단계를 더 강요한다.

루트는 가장 가까운 `.git` 조상이며 `--into`로 덮어쓴다.

이 README는 **설치되지 않는다**. 여기를 유지보수하는 사람에게 하는 말이지 skill을 읽는 agent에게
하는 말이 아니고, 설치본에 섞이면 agent가 자기 대상이 아닌 문서를 권위로 읽는다.

## 현재 담고 있는 것

PRD §11.2가 정한 아홉은 전부 서 있다: `introduce-vqapr`, `register-dataset`, `make-datamodel`,
`make-strategy`, `make-exchange`, `make-compliance`, `run-backtest`, `analyze-result`,
`inspect-workspace`. `_shipped.json`은 릴리스마다 `scripts/record_shipped_skills.py`가 갱신한다.

**열 번째는 축이 다르다.** `report-issue-dev`는 vqapr로 무엇을 하는 skill이 아니라 vqapr가
틀렸을 때 그것을 upstream `docs/issues/`에 돌려보내는 skill이다. 아홉의 description 중 어느
것으로도 "결함을 보고한다"는 요청이 발견되지 않기 때문에 별도 skill이다.

그 skill은 upstream에 **파일 하나를 쓰는 것만** 한다. 진단하려고 upstream을 읽는 것은 금지한다 —
testbed 발견의 값어치는 공개 표면만 가진 사람이 냈다는 데 있고, `src/`를 읽는 순간 그것이
사라진다. 번호(`NNN-`)도 주지 않는다: 그 이름은 소유자가 분류한 이슈의 것이고 `src/`가 결정
근거로 인용하므로, 판정되지 않은 보고가 그것을 가져가면 인용이 무엇을 뜻하는지 알 수 없게 된다.

## skill 하나를 어떻게 쓰는가

- 최상위의 디렉터리 하나 = skill 하나. 그 안의 `SKILL.md`가 required entrypoint다.
- 보조 자료는 `references/`, `scripts/`, `examples/`, `assets/`에 둔다.
- **참조는 SKILL.md에서 한 단계 깊이까지만.** reference가 다시 reference를 가리키면 읽는 쪽이
  부분 읽기로 끝내고 불완전한 정보를 얻는다.
- 경로 구분자는 언제나 `/`. 역슬래시로 적힌 키는 출하 이력 표에서 다른 항목이 되고, 그러면
  손대지 않은 설치본이 다른 플랫폼에서 `modified`로 판정된다.
- `README.md`와 `_shipped.json`은 skill로 취급되지 않는다 (`skillset._NOT_A_SKILL`).

## 출하 이력 표

`_shipped.json`은 `{"<skill>/<상대 경로>": {sha256: 그 내용이 처음 출하된 릴리스}}`다. 설치본이
우리가 준 것인지를 **manifest가 아니라 내용**으로 답하기 위한 것이다 — skill directory는 손으로
복사되거나 clone되어 manifest 없이 도착할 수 있다.

**표에서 항목을 제거하지 않는다.** 오래된 릴리스의 해시를 지우면 그 판을 설치해둔 사용자는
손대지 않았는데 `modified` 판정을 받고, 확인 절차를 습관적으로 건너뛰는 법을 배운다.

## skill이 담당하는 것

package는 deterministic하게 판정만 하고, **대화는 전부 여기가 담당한다**(PRD §2.6).

- **등록 이전부터 개입한다.** error 이후가 아니다. `DATE`가 관측일인지 공개 시각인지 묻고,
  look-ahead 위험을 설명하고, 후보를 제시한다(`UC-AGENT-001`).
- **package가 원리적으로 검증할 수 없는 것을 경고한다.** 이동평균·누적합·순위처럼 등록
  query에 쓰면 미래를 반영할 수 있는 패턴, stale price로 읽힐 컬럼 선택(`UC-AGENT-002`).
- **데이터가 증명하는 것과 이름으로만 아는 것을 구분한다.**
- 경제적 의미나 authority를 바꾸는 선택은 **user가 판단하게 한다.**

## skill이 하지 않는 것

- package validation을 우회하지 않는다.
- missing semantics를 추측하지 않는다.
- 근거가 확인되기 전에 binding을 확정하지 않는다.
- **refusal을 산문으로 다시 말하지 않는다.** refusal은 status·stage·cause와 `fix`·`requirement`·
  `observed`·`source`를 스스로 싣는다(PRD §11.2, record `171`). 봉투가 못 싣는 도메인 지식 —
  왜 naive timestamp를 대신 변환하지 않는가 같은 것 — 만 그것을 소유하는 skill의 reference에
  남는다.
