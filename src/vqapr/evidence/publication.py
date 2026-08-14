"""staging -> flush -> atomic visible.

구현할 것
    chunk flush    row 수 또는 buffer byte 한도 도달 시 immutable chunk로
    finalize       chunk manifest와 metadata를 원자적으로 publish
    가시성 규칙     payload + metadata + catalog record가 **모두** 커밋된 뒤에만 visible

왜 flush와 publish가 한 파일인가
    지켜야 할 불변식이 **하나**다 — "staging chunk만 존재하는 incomplete table은 reusable
    artifact로 보이지 않는다." 두 파일에 걸치면 한쪽만 고치는 사고가 난다.

buffer 크기와 compression은 run identity가 아니다
    storage tuning이다. 예를 들어 10,000 rows 또는 64 MiB 중 먼저 도달한 조건으로 flush할 수
    있고, 그 값이 바뀌어도 경제적 결과는 같다.

buffered-until-finalize가 만들어내는 성질
    run 중에는 아무것도 보이지 않으므로 **같은 run 안에서 자기 기록을 되읽는 경로가 구조적으로
    없다.** reporting은 run이 끝난 뒤에 읽는다.

한 invocation에서 기록한 row는
    그 invocation의 결과 검증이 성공한 뒤에만 정상 evidence로 확정된다.

`UC-ARTIFACT-003`
"""
