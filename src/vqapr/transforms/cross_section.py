"""한 시점의 종목들을 서로 비교한다.

구현할 것
    rank              횡단면 순위
    zscore            횡단면 표준화
    demean            횡단면 평균 제거
    winsorize         극단값 절단
    quantile_buckets  분위 버킷 배정 + **사용된 breakpoint 값과 기준 표본 크기를 함께 반환**

왜 quantile_buckets가 breakpoint를 돌려주나
    Fama-French 스타일 double sort에서 membership을 재사용 가능한 결과로 만들려면 breakpoint가
    출력과 같은 모양의 컬럼으로 남아야 한다(architecture §11.1). 그리고 "KOSPI 종목만으로
    breakpoint를 만들어 양 시장에 적용" 같은 선택이 기록되어야 재현된다.

결측은 여기서 다루지 않는다
    호출자가 `missing.py`로 먼저 해소한다. 조용히 빼고 계산하면 어느 종목이 왜 빠졌는지가
    사라진다.

`UC-FACTOR-001`
"""
