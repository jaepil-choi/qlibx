"""data — 그때 무엇을 읽을 수 있는가.

두 층으로 갈라져 있다.
    물리   `sources.py`      어디에 어떻게 쌓여 있나
    의미   `datasets.py`     그 값이 무엇인가

가른 이유는 `exchange/execution_table.py`가 **물리 층만 재사용하고 의미 층은 쓰지 않기**
때문이다. 한 파일이면 그 재사용이 import 그래프에 보이지 않는다(architecture §6.2).

이 층의 불변식
    소비자는 Store 핸들을 받지 않는다. requirement를 선언하면 `flow/views.py`가 bounded
    View를 준다. PIT은 규칙이 아니라 **접근 불가능성**으로 강제한다(architecture §2.2).
"""
