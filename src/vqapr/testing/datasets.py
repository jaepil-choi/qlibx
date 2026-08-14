"""픽스처 dataset — **같은 데이터를 두 배치로.**

구현할 것
    넓은 표 배치와 field=폴더 배치로 **같은 논리적 데이터**를 만드는 빌더
    등록까지 마친 DatasetRegistration

왜 두 배치인가
    architecture §16의 체크리스트 항목 — *"같은 dataset을 넓은 표에서 field별 폴더로 바꿔도
    소비자의 requirement 선언이 변하지 않는다."* 이것은 **픽스처가 두 배치를 만들고 같은
    테스트를 parametrize할 때만** 검증된다.

    픽스처 설계가 곧 그 체크리스트 항목이라, 처음부터 이 모양이어야 나중에 안 고친다.

포함해야 하는 변형
    ragged panel (종목마다 행 수가 다름) · field마다 available_at이 다른 경우 ·
    coverage가 부족한 구간
"""
