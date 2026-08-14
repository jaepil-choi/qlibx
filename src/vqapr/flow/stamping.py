"""기록 행에 봉투를 찍는다.

구현할 것
    user가 쓴 컬럼 옆에 다섯을 찍는다
        run_id       어느 run
        producer_id  누가 썼나 (strategy_id 또는 datamodel_id)
        stage        `runtime/events.py`의 EventKind — 이 timestamp가 어느 축에 있나
        event_time   그 stage의 evaluation time
        sequence     같은 (stage, event_time) 안의 순서

왜 Flow가 찍나
    `available_at`에 대해 말한 것과 같은 논리다 — **생산자가 주장하지 않는다.** Model이 자기
    timestamp를 쓸 수 있으면 아무 값이나 쓸 수 있고 읽는 쪽이 믿을 수 없다. Flow는 자기가 지금
    어느 이벤트를 dispatch 중인지 안다(architecture §9.1).

왜 stage가 필요한가
    나중에 테이블을 여는 쪽에서는 timestamp 컬럼 하나가 보이는데 그것이 무슨 시각인지 알 방법이
    없다. 판단한 시각(2024-03-06 04:00)과 그 값이 유효해지는 시각(2024-06-28 15:30)은 다른
    의미다. **어느 축인지 모르는 timestamp는 timestamp가 아니다.**

예약 컬럼 — 선언 시점에 막는다
    TableSpec이 위 다섯 중 하나를 선언하면 **run 시작 전에 실패한다.** 쓰는 시점에 막으면 이미
    그 이름으로 코드를 짠 뒤다.

sequence는 (stage, event_time) 안에서 센다
    그래야 한 판단 안에서 세 번째로 쓴 행이 세 번째로 복원된다.

왜 별도 파일인가
    `simulation.py`와 `materialize.py` **둘 다** 부른다.

미결
    materialize가 찍을 stage 값이 `runtime/events.py`의 어휘에 아직 없다. DataModel
    materialization은 run()이 아니고 DECISION도 아니다. 후보는 MATERIALIZE 추가 또는
    DATA_AVAILABLE 사용이며, recorder를 쓰는 DataModel이 실제로 나올 때 정한다.
"""
