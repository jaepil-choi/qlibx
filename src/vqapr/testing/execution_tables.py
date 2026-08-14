"""픽스처 체결 테이블.

구현할 것 — 네 상황이 전부 있어야 한다
    정상                     행 있고 is_tradable=true, 가격 양수
    is_tradable=false        상장돼 있으나 거래 불가        -> zero-dealt
    행 없음                   그 시점 이 venue에 없다        -> zero-dealt
    is_tradable=true + 가격 없음/음수/비유한                -> **batch 실패**

왜 네 번째가 중요한가
    앞의 셋과 급이 다르다. 앞은 고칠 것이 없는 시장 사실이고 이것은 **거래할 수 있다고 선언해
    놓고 가격을 주지 않은 것**이라 연구자가 고칠 수 있고 고쳐야 한다(architecture §6.1).

이름이 `exchange/venues/`와 다른 이유
    저기는 진짜 venue 구현이고 여기는 픽스처 테이블이다. `testing/venues.py`라고 하면 두
    개념이 섞인다.
"""
