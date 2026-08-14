"""픽스처 계좌.

구현할 것
    초기 AccountSnapshot 빌더 (cash만, cash + position, signed position)
    이력이 있는 Account — stop-loss와 cooldown 테스트가 `account_history`를 읽어야 한다

왜 이력이 필요한가
    `UC-ACCOUNT-HISTORY-001`은 **strategy state 없이** stop-loss를 표현할 수 있어야 한다고
    요구한다. 그것을 검증하려면 memory가 빈 Model에게 줄 이력이 있어야 한다.
"""
