"""ObservationStore 포트의 구현들.

memory   테스트가 duckdb 없이 도는 길
duckdb   parquet 위의 실제 조회 경로

**두 구현은 관측 가능한 결과가 같아야 한다.** 저장 방식이 달라도 artifact identity, validation,
durability, publication outcome이 같다는 PRD §9.5의 요구가 여기에 걸린다.
"""
