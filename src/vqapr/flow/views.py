"""requirement -> bounded View. **Store 핸들을 갖는 유일한 곳.**

구현할 것
    소비자의 DataRequirement를 받아 `data/resolution.py`로 물리 질의를 만들고,
    `data/store.py`로 조회해 `data/windows.py`의 ModelWindow를 만든다.
    available_at <= evaluation_time 상한이 적용되는 지점이 여기다.

왜 이 파일이 존재하나
    PIT은 규칙이 아니라 **접근 불가능성**으로 강제해야 한다. 규칙은 잊히고 캡슐화는 잊히지
    않는다. `store.query(...)` 한 줄이면 look-ahead가 가능하고 리뷰로 막는 것은 확장되지
    않는다(architecture §2.2).

    그래서 Store 핸들은 **어디에도 전달하지 않는다.** 소비자는 requirement를 선언할 뿐이다.

각 소비자마다 자기 evaluation time이 있다
    StrategyModel과 alpha는 decision time, order conversion과 pre-execution validation은
    execution time, monitoring은 monitoring time(PRD §3.2).

`materialize.py`도 이 파일을 쓴다
    창 구성 경로가 하나여야 PIT 처리가 한 곳에만 존재한다.
"""
