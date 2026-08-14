"""관측 조회 포트.

구현할 것
    ObservationStore   해석된 질의를 받아 Rows를 돌려주는 protocol

왜 포트인가
    PRD §9.5가 project마다 local 또는 external storage를 **선택**할 수 있어야 한다고 요구한다.
    선택이지 저작이 아니므로 구현은 package가 소유한다(`stores/`).

**핸들이 소비자에게 가지 않는다.**
    이 protocol의 인스턴스를 갖는 것은 `flow/views.py` 하나뿐이다. 소비자는 requirement를
    선언할 뿐이다. `store.query(...)` 한 줄이면 look-ahead가 가능하고, 리뷰로 막는 것은
    확장되지 않는다(architecture §2.2).

구현이 둘 이상이라 protocol이 정당하다
    `stores/memory.py`는 테스트가 duckdb 없이 도는 길이고 `stores/duckdb.py`가 실제 경로다.
    구현이 하나였다면 protocol을 두지 않았을 것이다(architecture §10).

`scan.py` 위에 선다
    물리 파일을 여는 것은 `scan.py` 하나이고, 이 포트는 그 위에서 **창 조회**를 담당한다.
    등록 검증(스캔)과 체결 테이블(점 조회)은 같은 `scan.py`를 쓰되 이 포트를 거치지 않는다.
"""
