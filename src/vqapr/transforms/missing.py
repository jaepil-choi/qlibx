"""결측을 명시적으로 해소한다.

구현할 것
    drop_missing(signal)              -> (Signal, 빠진 종목 집합). **무엇이 빠졌는지 반환한다**
    require_complete(signal, universe) -> Signal. 불완전하면 실패

왜 빠진 종목을 값으로 돌려주나
    어떤 종목이 왜 제외되었는지가 호출자에게 값으로 돌아와야 result evidence에 실린다
    (`UC-BUILTIN-001`). 함수 안에서 조용히 처리하면 그 사실이 사라진다.

**fill_missing을 제공하지 않는다.**
    0으로 채우기는 "포지션 없음"이라는 경제적 주장이고, 평균으로 채우기는 연구 결정이다.
    built-in이 대신 말하면 안 된다.

왜 weighting이 아니라 여기 있나
    다루는 대상이 weight가 아니라 signal이다. `portfolio/weighting.py`는 결측을 다루지 않으며,
    호출자가 이 함수들로 먼저 해소한 뒤 부른다.
"""
