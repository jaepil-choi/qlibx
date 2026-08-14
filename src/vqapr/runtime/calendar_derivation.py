"""calendar를 유도해야 할 때 — 규칙은 닫힌 집합이고, 적용은 순수하다.

상황
    사용자가 가진 것이 daily 시세뿐이고 거래소 calendar 파일이 없다. **가장 흔한 출발점이다.**

구현할 것
    유도 규칙의 **닫힌 집합**과 각각의 검증
        all_instrument_date_union   하루라도 거래된 날이 session. 한 종목의 결측에 무너지지 않는다
        single_reference_instrument 그 종목이 정지되면 session이 사라진다. **위험**
        index_series                안전. 다만 지수 데이터가 있어야 한다
    apply(rule, dates, session_times) -> SessionCalendar

**날짜를 인자로 받는다. 읽지 않는다.**
    calendar의 원천은 사용자가 이미 등록한 dataset이다 — 일별 시세를 등록했다면 그것이 곧 원천이다.
    그런데 그렇게 하면 `runtime/`이 데이터를 읽는 것처럼 보인다. 그렇지 않다. **둘로 가른다.**

        읽기   등록된 dataset의 distinct 날짜를 뽑는다        data 경로 (`data/scan.py`)
        적용   날짜 집합 + 선언된 규칙 -> frozen SessionCalendar   여기. 순수

    `transforms/`와 `portfolio/`가 panel을 인자로 받는 것과 같은 규칙이다. 직접 읽으면 그 접근이
    declared requirement를 거치지 않아 **calendar가 어느 dataset에서 왔는지 lineage에 남지 않는다.**

    그리고 `runtime/`이 `data/`를 import하지 않아야, "cadence를 데이터에서 유도하지 않는다"(§3.1)를
    코드 구조가 계속 말해준다.

날짜는 유도되고 시각은 유도되지 않는다
    daily 행에는 `2024-03-05`만 있고 `15:30 KST`가 없다. 그 시각은 이미 `available_at` 규칙
    (`data/availability.py`)이 담고 있으므로 새로 요구하지 않고 같은 선언을 재사용한다.

유도된 calendar는 project 선언이 된다
    한 번 유도하고 매번 다시 만들지 않는다. 결과는 frozen SessionCalendar로 workspace에 남고
    (`workspace.py`), 선택된 규칙과 원천 dataset이 함께 기록되어 "이 run의 session이 어디서 왔나"를
    감사할 수 있다.

§3.1의 금지를 그대로 지킨다
    아무도 선언하지 않았는데 가격 coverage로 session이 만들어지는 경로는 **없다.** 사용자가 규칙을
    골라 명령을 실행해야만 calendar가 생긴다. §3.1의 금지는 **package의 추측**을 향한 것이지
    user의 선언을 향한 것이 아니었다.

`data/availability.py`와 대칭이다
    package는 추측하지 않는다 -> user가 근거와 함께 선언 -> package가 결정적으로 검증 ->
    규칙이 frozen input에 남는다. 두 파일이 같은 모양이어야 그 원칙이 하나임이 보인다.

`UC-CALENDAR-001`
"""
