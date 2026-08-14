"""검증 helper.

구현할 것
    intended / requested / dealt / committed 비교
    결정성 — 같은 frozen input이 같은 결과를 만드는지
    mutation 없음 — 실패가 position/cash/version/journal을 하나도 바꾸지 않았는지
    lineage — 읽은 dataset이 dependency에 있고 안 읽은 것이 없는지

왜 helper가 필요한가
    위 넷은 거의 모든 spine 테스트가 확인해야 하는 것이다. 각 테스트가 따로 쓰면 무엇을
    주장하는지가 assertion 뭉치에 묻힌다.
"""
