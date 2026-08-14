"""ref -> 인스턴스.

구현할 것
    ComponentRef의 path를 import하고 config로 인스턴스를 만든다
    import 실패 · 타입 불일치 · 잘못된 config를 **bounded error**로 변환한다

**partial registration을 만들지 않는다.**
    로딩 중 실패하면 아무것도 등록되지 않은 상태로 끝난다. 절반만 등록되면 이후 run이 무엇을
    쓰는지 알 수 없다(PRD §12.3).

source를 찾거나 load할 수 있다는 사실만으로 compatibility가 증명되지 않는다
    로딩은 첫 관문일 뿐이고 계약 준수 판정은 conformance가 한다(`registration.py`).

security sandbox가 아니다
    local code validation은 sandbox나 dependency installer를 의미하지 않는다(PRD §12.3).
"""
