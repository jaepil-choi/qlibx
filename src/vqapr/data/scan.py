"""물리 층을 여는 유일한 곳 — 창도 점도 아닌 **스캔**.

구현할 것
    open_source(spec) -> Relation      SourceSpec을 스캔 가능한 형태로 연다
    columns(spec)                       존재하는 컬럼과 추론된 타입
    distinct(spec, field)               한 컬럼의 distinct 값 (calendar 유도의 입력)
    key_is_unique(spec, fields)         null 없이 유일한지 + 위반 예시 bounded 반환
    format 판별                          csv · parquet · 디렉터리(하위 전부)

왜 별도 층인가
    같은 물리 파일에 **서로 다른 모양의 질문 셋**이 온다.

        이 컬럼이 있나 · 이 key가 유일한가     등록 검증    **스캔**   여기
        available_at <= t인 최근 N행           소비자        창        `store.py`
        trade_at = t인 행                       Exchange      점        `exchange/`의 체결 테이블

    셋 다 같은 파일을 열지만 질문이 다르므로 조회 계약도 다르다.

**`sources.py`에 넣지 않는다**
    그것은 선언(값)이다. I/O를 붙이면 값이 아니게 되고, 등록 선언을 만드는 것만으로 파일이 열린다.

**`stores/duckdb.py`에 넣지 않는다**
    그러면 `exchange/execution_table.py`가 특정 backend를 import하게 되어 **venue가 storage 구현에
    묶인다.** §6.2가 물리 층만 재사용하기로 한 것이 불가능해진다.

없으면 무엇이 깨지나
    등록 검증이 `ObservationStore`를 거쳐야 하는데 그것은 창 조회라 *"이 key가 전체에서 유일한가"*를
    물을 수 없다. 억지로 물으려면 lookback 없는 전체 조회를 허용해야 하고, **그 구멍이 곧 look-ahead
    경로가 된다.**

여기서 하지 않을 것
    의미 해석. 어느 컬럼이 `available_at`인지는 `datasets.py`가, 어느 lookback이 몇 행인지는
    `resolution.py`가 이미 정했다. 이 파일은 컬럼 이름과 파일 경로만 안다.

규모에 대해
    실제 source는 수백 MB~GB다. `key_is_unique`는 전체 스캔이므로 위반 예시를 **bounded**하게
    돌려주고(PRD §2.6) 전체를 메모리에 올리지 않는다.
"""
