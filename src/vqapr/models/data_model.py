"""DataModel — 값을 만든다.

구현할 것
    DataModel(Model)
        compute(context: DataModelContext) -> Rows

무엇이 이 역할을 정의하나
    **execution을 거치지 않는다.** 시가총액이나 베타를 "체결한다"는 말은 성립하지 않으므로
    계산이 execution 앞에서 끝나고, 그 자체로 완결된 workflow다(PRD §2.3, `UC-MODEL-001`).

    이 파일이 `strategy_model.py`와 갈리는 지점은 import 한 줄이다 — 저쪽은 PortfolioIntent를
    import하고 이쪽은 하지 않는다.

available_at을 주장하지 않는다
    계산 결과의 available_at은 생산자가 아니라 package가 정한다. 실제로 읽은 것에서 나오므로
    위조할 수 없다(`flow/materialize.py`, architecture §4.5).

warm-up이 없다
    데이터가 부족하면 그 시점 행을 만들지 않으면 된다. "판단하지 않았음"을 기록할 이벤트가
    없고, 부족한 coverage는 그 결과를 읽는 쪽의 CoverageRequirement가 잡는다.

Model state를 쓰면 순차 생성이 된다
    trigger 순서대로 호출되어야 같은 값이 나오므로 병렬 계산과 부분 재생성이 불가능해지고,
    **그 사실이 출력에 남아야 한다.** 남지 않으면 나중에 구간만 다시 만들려는 시도가 조용히
    다른 값을 만든다.

recorder가 필요한 이유
    출력으로 표현할 수 없는 것이 있다. 출력은 살아남은 종목당 한 행이고, "이 30종목을 왜
    뺐는가"는 카디널리티도 key도 다르다.

`UC-MODEL-001` `UC-MODEL-002` `UC-MODEL-003`
"""
