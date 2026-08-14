"""preview / apply / update / remove.

구현할 것
    dry-run preview   target, 생성·수정할 exact path, instruction file의 managed block,
                      skill resource version, validation command를 실행 전에 보여준다
    apply / update / remove

**project file을 소유한다고 가정하지 않는다.**
    기존 `AGENTS.md` `CLAUDE.md` 같은 instruction file을 발견하고 **vqapr가 소유하는 marked
    block만** 추가·갱신·제거한다. supported instruction file이 없으면 creation target을
    preview하고 user가 요청한 경우에만 새로 만든다.

idempotent
    같은 target과 version으로 반복 실행해도 duplicate block, duplicate skill, 의미 없는 diff를
    만들지 않는다.

사용자가 고친 파일을 덮지 않는다
    생성한 skill file이 수정되었으면 content fingerprint 차이를 감지하고 **명시적 확인 없이
    덮어쓰지 않는다.**

remove의 경계
    vqapr-owned block과 확인된 generated file만 제거하며 instruction file의 나머지 내용이나
    project artifact를 삭제하지 않는다.

결과에 package version, skill schema/version, target type을 기록하고 target별 structure를
validation한다.

`UC-ONBOARD-001`
"""
