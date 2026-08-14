"""등록 이후 바뀌었는가.

구현할 것
    source 해시 계산
    등록된 fingerprint와 현재 상태의 비교
    drift 판정

**drift는 compute 전에 거부한다.**
    등록 뒤 source나 contract가 바뀌면 이전 registration을 암묵적으로 latest code에 연결하지
    않는다. 연결하면 "그때 그 전략"이라고 부르는 것이 실제로는 다른 코드가 된다
    (`UC-EXTENSION-002`).

이후 research 또는 execution은 user가 선택한 **exact registered version**을 사용하고 실제
dependency를 result에 남긴다.
"""
