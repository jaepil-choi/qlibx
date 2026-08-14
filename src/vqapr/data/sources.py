"""물리 배치 — 어디에 어떻게 쌓여 있나.

구현할 것
    SourceSpec       source_id, path(디렉터리면 하위 전부), 선택적 field_partition
    FieldPartition   key(파티션 키, 폴더 이름이 field 이름이 된다) + value(파일 안의 값 컬럼)

field_partition이 왜 source의 성질인가
    field가 많고 성긴 데이터(재무 계정 수백 개)는 넓은 표가 낭비다. 그때는 field를 폴더로
    올린다. 그러나 **소비자는 이 차이를 보지 않는다** — `fields=("bps",)`라고 쓰면 resolver가
    컬럼 선택으로 번역할지 경로 선택으로 번역할지 정한다(`resolution.py`).

    dataset 위로 올리면 소비자가 "폴더인가 컬럼인가"로 분기하게 되고, 나중에 배치를 바꿀 때
    dataset 정의와 소비자 코드가 같이 바뀐다. 배치는 성능 결정이고 의미가 아니다.

한 디렉터리 = 한 스키마
    폴더로 나누는 핵심은 저장 크기가 아니라 **파티션 키가 스키마를 결정한다**는 것이다.
    item을 컬럼으로 두면 value 하나에 double과 string이 섞인다.

이 파일은 `exchange/execution_table.py`도 재사용한다
    경로·디렉터리·파티션은 저장 방식의 문제이지 의미의 문제가 아니다. 두 벌 만들면 hive
    지원 같은 것을 두 번 구현하게 된다.
"""
