"""창 — 사각형 하나.

구현할 것
    ModelWindow       evaluation_time, instruments, observations(requirement) -> ObservationBatch
    ObservationBatch  Rows + requested/actual coverage
    AccessRecord      실제로 읽은 것. lineage의 입력

창은 (선언 종목 x 선언 lookback) 사각형 하나다
    횡단면 회귀는 1 x N, 20일 이동평균은 20 x N, 5년 rolling beta는 1260 x N. **모양이 다른 게
    아니라 비율이 다르다.** "횡단면 창"과 "시계열 창"을 별도 개념으로 두지 않는다.

    이것이 가능한 이유는 계산식 DSL을 두지 않고 사각형을 통째로 넘기기 때문이다. DSL을 쓰면
    rolling 연산자와 횡단면 연산자를 따로 만들어야 하고 그때 두 개념이 갈린다.

물리 배치는 여기까지 올라오지 않는다
    넓은 표에서 왔든 field 폴더에서 왔든 창은 같은 사각형이다. 번역은 `resolution.py`가 끝냈다.

왜 coverage를 함께 담나
    rows보다 적은 행만 존재하면 있는 만큼 반환하고 requested/actual을 access evidence에
    기록한다. 그래야 소비자가 "적게 왔다"를 알 수 있다(PRD §3.5).

읽지 않은 dataset은 dependency가 아니다
    AccessRecord가 실제 접근에서 만들어지므로 lineage가 선언이 아니라 사실을 담는다.
"""
