"""시작 전에 검사하고 동결한다.

구현할 것 — 검사 목록
    trigger timezone <-> calendar timezone
    intent direction <-> Exchange permitted side
    Exchange <-> AccountMode
    instrument listing과 quantity rule 존재
    모든 component requirement 충족 가능
    intent가 다룰 수 있는 모든 instrument에 대해 Exchange가 listing을 갖고 있음
    모든 (instrument 종류, 방향, 실행 시점)에 **정확히 하나의** CostRule이 매칭됨
    initial account 불변식
    initial_state_ref가 선택한 Model implementation과 compatible하고 committed 상태임
    schedule 결정성 — 같은 frozen input이 같은 Timeline을 만든다. **두 리스트를 비교한다**
    선언된 각 Constraint의 requirements()가 등록된 dataset으로 충족 가능함
    monitoring cadence의 timezone <-> calendar timezone

execution이 있는 run에만 적용되는 넷
    체결 테이블이 선언되어 있고 FillConvention.trade_price가 가리키는 컬럼이 존재함
    schedule이 만드는 **모든 체결 시각**에 trade_at 행이 존재함 (세션 축으로만 확인한다 —
        종목별 결측은 체결 시점에 zero-dealt로 다뤄지는 정상 결과다)
    is_tradable=true인 행의 선언된 가격이 **유한하고 양수**임
    **판단 시각과 체결 시각이 같지 않음**

    DataModel 연구와 signal 분석은 체결 테이블 없이 완결된다.

왜 판단 시각 = 체결 시각을 막나
    전략이 자기가 체결할 가격을 보고 판단한 것이다. 미래를 본 것은 아니라 look-ahead는 아니지만
    **현실에서 불가능하고 성과를 조용히 부풀린다.** 명시적으로 선언한 경우에만 통과시키고 그
    사실을 result limitation에 남긴다. 검사 대상은 offset_sessions==0이 아니라 **시각의
    동일성**이다 — 표준 daily-close 흐름이 이미 offset 0이다.

왜 preflight가 필요한가
    호환되지 않는 조합이 중간에 실패하면 이미 commit된 상태가 남는다. 시작 전에 실패하면
    FAILED_WITHOUT_MUTATION으로 끝난다.

initial_state_ref=None은 fresh Model을 뜻한다
    이전 또는 latest state를 **자동 탐색하지 않는다.**
"""
