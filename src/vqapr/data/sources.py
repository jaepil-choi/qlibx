"""물리 배치 — 어디에 어떻게 쌓여 있나.

구현할 것
    SourceSpec       source_id, path(디렉터리면 하위 전부), format, 선택적 field_partition
    FieldPartition   key(파티션 키, 폴더 이름이 field 이름이 된다) + value(파일 안의 값 컬럼)

format이 필요한 이유
    실제 project는 csv로 시작한다. parquet만 전제하면 첫 등록부터 막힌다. 확장자로 추론하되
    명시할 수 있어야 하며, **parquet 변환을 요구하지 않는다** — 사용자가 성능을 위해 미리 변환하는
    것은 자유지만 package가 강제하면 "저장 방식은 소비자에게 안 보인다"가 거짓이 된다.

**이것은 선언(값)이고 파일을 열지 않는다.**
    여는 것은 `scan.py`다. 여기에 I/O를 붙이면 등록 선언을 만드는 것만으로 파일이 열린다.

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
