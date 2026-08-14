"""portfolio — 값을 배분으로. 순수 leaf.

주의 — 이 이름은 nautilus와 반대 뜻이다
    nautilus의 `portfolio/`는 캐시에서 읽어 노출·마진·미실현 손익을 집계하는 **State 쪽**
    컴포넌트이고, 우리 `account/` + `valuation/`이 거기 해당한다. 우리 `portfolio/`는 값을
    배분으로 바꾸는 **Decision 쪽** 순수 함수다. 두 코드베이스를 오가면 반드시 걸린다.

leaf 규칙
    `weighting.py`와 `optimize.py`는 `domain`(+solver) 외에 아무것도 import하지 않는다.
    필요한 값은 전부 인자로 받는다.
"""
