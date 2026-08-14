"""선언 x calendar -> 정렬된 frozen 이벤트 열.

구현할 것
    build_timeline(...)  SessionCalendar와 선언들(TriggerPolicy, FillConvention, valuation/
                         monitoring cadence)을 결합해 전체 이벤트 열을 만든다
    Timeline             불변. 같은 입력이면 같은 열

**이것은 clock이 아니다.**
    모든 시각이 선언에서 나오므로 데이터가 도착해서 시각이 생기는 일이 없고, 따라서 전체
    열이 시작 전에 계산된다. `Clock`이라고 부르면 `now()`와 중간 삽입을 붙이고 싶어지는데,
    그 둘이 재현성을 깨는 정확한 방법이다(architecture §2.1).

여기서 얻어지는 것
    preflight의 "schedule 결정성" 검사가 **두 리스트를 비교하는 일**이 된다(architecture §12).

여기서 하지 않을 것
    시간을 진행시키는 것 외에 아무 의미도 알지 않는다. StrategyModel도 Exchange도 모른다.
    이 객체를 Model에게 넘기지 않는다 — 넘기면 미래 session이 그대로 보인다(architecture §5.1).
"""
