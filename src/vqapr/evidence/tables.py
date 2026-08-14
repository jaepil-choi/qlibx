"""무엇을 기록할지 미리 선언한다.

구현할 것
    TableSpec   table_id + 컬럼 이름/타입. portable scalar type으로 제한
    예약 컬럼    run_id · producer_id · stage · event_time · sequence

**예약 컬럼을 선언하면 run 시작 전에 실패한다.**
    쓰는 시점에 막으면 이미 그 이름으로 코드를 짠 뒤다. CostRule의 기간 겹침을 선언 시점에
    거부하는 것과 같은 자리다. 없으면 model이 자기 stage 컬럼으로 진짜 것을 가릴 수 있다.

TableSpec 위반은 조용히 행을 버리는 것이 아니라 **run 실패**다
    기록이 결과를 바꾸면 안 되지만 schema 위반은 드러나야 하고, 결정적이므로 재현에 문제가 없다.

왜 `recorder.py`와 다른 파일인가
    이것은 Model이 **선언**하는 것이고 저것은 Flow가 **수집**하는 것이다. `models/model.py`의
    tables()가 이 타입을 반환한다.
"""
