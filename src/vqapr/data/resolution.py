"""requirement -> 물리 질의 번역.

구현할 것
    프레임워크 이름 -> 물리 접근 번역
        넓은 표     컬럼 선택
        field 폴더  경로 선택 (조건 평가가 아니라 파일을 안 연다)
    available_at <= evaluation_time 상한
    lookback을 **store query에 직접 반영**

**전체를 읽고 Python에서 자르지 않는다.**
    lookback이 store query까지 그대로 내려가야 한다. 전체 history를 먼저 읽은 뒤 잘라내는
    경로를 bounded access로 간주하지 않는다(`UC-LOOKBACK-001`).

`store.py`와 왜 다른 파일인가
    여기는 **의미를 물리로 옮기는 번역**이고 저기는 **조회 포트**다. 새 물리 배치가 생기면
    이 파일이 바뀌고, 새 backend가 생기면 저 파일의 구현이 는다. 변경 이유가 다르다.

소비자 코드가 배치에 따라 달라지지 않는다
    재무를 폴더에서 넓은 표로 바꿔도 DataRequirement 선언은 그대로다(`UC-DATA-003`).
"""
