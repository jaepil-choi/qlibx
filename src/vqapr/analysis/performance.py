"""저장된 mark -> 성과.

구현할 것
    NAV 시계열 · 기간 수익률 · 누적 수익 · drawdown · 변동성

입력은 저장된 committed mark 기록뿐이다
    가격 dataset을 다시 읽어 계산하지 않는다. 그렇게 하면 execution을 거치지 않은 수치가
    성과로 나온다.

renderer를 부르지 않는다
    값만 만든다. 표현은 `renderers.py`가 한다 — 그래야 "renderer가 달라도 값이 같다"가
    구조적으로 보장된다.
"""
