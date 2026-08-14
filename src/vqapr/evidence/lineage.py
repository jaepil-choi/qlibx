"""무엇을 실제로 읽었는가.

구현할 것
    `data/windows.py`의 AccessRecord를 모아 dependency graph를 만든다
    각 result가 어떤 dataset의 어떤 field를 어떤 cutoff로 읽었는지 보존한다

**읽지 않은 dataset은 dependency가 아니다.**
    선언이 아니라 실제 접근에서 만들어지므로 lineage가 사실을 담는다. 선언 기반이면 "요구했지만
    안 읽은 것"이 dependency가 되어 재사용 판정이 과하게 좁아진다.

같은 artifact를 소비한 run들의 관계가 여기서 유도된다
    6개 버킷 run이 같은 membership artifact를 가리키면 "이 6개가 하나의 연구"라는 관계가
    graph에서 나온다. **별도 grouping 개념을 만들 필요가 없다**(architecture §11.1).

path-dependency와 actual-state dependency를 구분해 보존한다
    A의 배분이 계좌 A 기준으로 만들어졌고 계좌 C에서 재계산된 것이 아님을 lineage가 지켜야
    한다(`UC-ALPHA-PATH-001`).
"""
