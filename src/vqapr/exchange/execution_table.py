"""체결 테이블 — venue가 그 시점에 아는 것. 점 조회.

구현할 것
    ExecutionTableSpec   source(`data/sources.py` 재사용), 선택적 query,
                         trade_at_field, instrument_field, is_tradable_field,
                         price_fields (프레임워크 이름 -> 물리 컬럼, 하나 이상)
    조회                 trade_at = execution_time AND instrument IN (...) 을
                         **집합 단위로 한 번**

관측 dataset과 근본적으로 다르다
                  관측 dataset                  체결 테이블
    술어          available_at <= t (범위)      trade_at = t (점)
    결과          창. 여러 행                    정확히 한 행
    available_at  필수                          **없음**
    lookback      필수 선언                      없음
    읽는 주체     선언한 누구나                  **Exchange 하나**

왜 available_at이 없나
    available_at이 존재하는 이유는 관측자가 미래를 못 보게 하기 위해서다. 여기에는 관측자가
    없다 — Exchange는 관측하는 것이 아니라 **그 순간을 만든다.** 15:30에 체결하는 Exchange에게
    15:30의 가격은 지연을 두고 알게 되는 관측이 아니라 venue 상태 그 자체다.

왜 물리 층은 공유하고 의미 층은 안 쓰나
    `DatasetRegistration`이 요구하는 available_at·key_fields·fields는 창 조회를 위한 것이고
    여기엔 창이 없다. 억지로 끼워 맞추면 소비자가 "이 dataset은 창으로 읽나 점으로 읽나"를
    구분해야 한다. 반면 경로·디렉터리·파티션은 저장 방식의 문제라 재사용한다.

    파일을 여는 것은 `data/scan.py`이고 `data/store.py`(창 포트)는 거치지 않는다. `scan.py`가
    backend를 감추므로 **venue가 특정 storage 구현을 import하지 않는다.**

**Model이 여기 도달할 경로가 없다.**
    규칙이 아니라 경로의 부재다. 접근할 수 있으면 어느 종목이 그날 정지될지를 판단 시점에
    알게 되고, 일별 판단 + 촘촘한 체결 구성이 표현되지 않는다.

거래 가능 여부의 유도가 여기서 일어난다
    정지 이력이 없는 project는 is_tradable_field를 만드는 규칙을 query에 쓴다("거래대금 > 0"
    같은 것). 별도 DataModel도 별도 개념도 필요 없고, 선택된 규칙이 Exchange config에 남아
    frozen input이 된다(`UC-TRADABILITY-001`).

행이 없는 것과 false인 것을 구분한다
    행 있고 is_tradable=false  -> 상장돼 있는데 그 시점 거래 불가
    행 없음                     -> 그 시점 이 venue에 없다 (상장 전 / 상폐 후)

    **종목별로 물어보면 둘이 안 갈린다.** 집합으로 물어야 조회에 안 나온 것과 나왔는데 false인
    것이 구분된다. 따라서 집합 조회는 batch 단위 실행의 전제조건이다.
"""
