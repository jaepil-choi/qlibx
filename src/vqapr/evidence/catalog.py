"""저장된 결과를 찾고, 재사용 가능한지 판정한다.

구현할 것
    artifact 조회
    reuse 판정 — identity와 compatibility가 일치하는지
        artifact schema와 semantic type
        time / axis / universe / currency compatibility
        input·producer fingerprint
        path-dependency와 actual-state dependency
        terminal status와 coverage
        parent/member lineage

**reuse는 단순 path 복사가 아니다.**
    consumer가 위 항목을 검사한 뒤에만 producer rerun 없이 사용한다(PRD §9.6).

성공만 남기지 않는다
    성공, 실패, unsupported result, diagnostic, user decision을 catalog에 남겨 다음 연구의
    출발점으로 쓴다. 성공한 trial만 남기면 같은 실패와 중복 hypothesis를 반복한다(PRD §2.8).

`UC-RESEARCH-001`
"""
