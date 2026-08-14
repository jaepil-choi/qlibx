"""domain — 누구에게도 의존하지 않고 모두가 의존하는 어휘.

들어올 자격은 세 가지를 **모두** 만족해야 한다(architecture §10).

1. 둘 이상의 package가 쓴다. 한 곳만 쓰면 그 층에 둔다.
2. storage · venue · 시간 진행을 모른다.
3. 없으면 두 package가 같은 것을 서로 다르게 표현하게 된다.

**명사만 둔다. 동사는 층이 갖는다.** 계산 · 정책 · 상태는 여기 오지 않는다.

여기 두지 않기로 한 것과 그 이유
    Quantity/Price/Money 값 타입   precision의 소유자가 venue다(`exchange/listings.py`)
    AccountMode                    계좌의 성질이다(`account/account.py`)
    TriggerPolicy                  Model이 선언한다(`models/triggers.py`)
    Recorder protocol              봉투를 찍는 주체가 flow다(`evidence/recorder.py`)
    AccountSnapshot·FillBatch      생산자가 하나뿐이라 자격 1번 미달
    EPS 같은 상수                  qlib `constant.py`가 그렇게 시작해 region 문자열까지 갔다
"""
