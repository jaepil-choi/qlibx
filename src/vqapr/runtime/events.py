"""무슨 일이 어떤 순서로 일어나는가.

구현할 것
    Event      각 이벤트가 자신의 evaluation time과 종류를 갖는다
    EventKind  **고정 우선순위**
               DATA_AVAILABLE -> DECISION -> EXECUTION -> FILL_COMMIT
               -> VALUATION -> MONITORING -> FINALIZE

왜 고정인가
    설정 가능하게 만들면 재현성이 설정에 의존한다. 순서는 하나뿐이다(architecture §3.2).

DATA_AVAILABLE을 발화하는 코드는 없다
    이것은 이벤트가 아니라 `available_at <= t`에서 **등호가 성립한다는 것을 순서로 표현한
    것**이다. available_at = 15:30인 행은 15:30에 일어나는 어떤 일보다도 먼저 보이게 된다.

    적어두지 않으면 구현할 때 emit 주체를 찾게 된다. 찾을 것이 없다.

이 값은 evidence의 봉투에도 쓰인다
    `flow/stamping.py`가 기록 행에 찍는 `stage`가 이 어휘다. 자유 문자열로 두면 읽는 쪽이
    정규화하게 된다(architecture §9.1).
"""
