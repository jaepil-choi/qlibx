# Mapping Sources

이 디렉터리는 DataGuide item semantic mapping처럼 전략 feature 의미를 결정하는 reviewed mapping source of truth를 둔다.

현재 기대 파일:

- `dataguide_statement_mapping.csv`

이 파일은 `scripts/outputs/dataguide_dwfng_mapping.csv` 같은 생성 output을 사람이 검토한 뒤 승격한 운영 mapping이다. `scripts/build_fng_statement_parquet.py`는 이 CSV를 canonical mapping source로 읽고, `data/preprocessed/dataguide_statement_mapping.parquet` mirror와 derived joined parquet을 생성한다.

Generated output이나 임시 분석 결과는 이 디렉터리에 두지 않는다.
