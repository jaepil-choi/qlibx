"""duckdb/parquet ObservationStore.

구현할 것
    ObservationStore protocol의 구현. `resolution.py`가 만든 질의를 duckdb에 위임한다.
    넓은 표는 컬럼 선택, field 폴더는 경로 선택으로 번역된 결과를 그대로 받는다.

여기서 하지 않을 것
    의미 해석. 어느 컬럼이 무엇인지, 어느 lookback이 몇 행인지는 `resolution.py`가 이미 정했다.
    이 파일이 그것을 다시 정하면 배치별로 결과가 갈린다.
"""
