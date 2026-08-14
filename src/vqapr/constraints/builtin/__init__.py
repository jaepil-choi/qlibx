"""package가 출하하는 constraint.

현재 둘뿐이다(PRD §7).

    no_short          w_i(t) >= 0
    single_name_cap   w_i(t) <= max(10%, w_index_i(t))

package가 제공하는 sector · turnover · liquidity · leverage · gross/net exposure 정책과
blocking·severity·override policy는 future work다. user가 `constraint.py`의 계약으로 표현할 수
있는 것을 직접 작성하는 것은 막지 않는다.

**이 둘은 특권을 갖지 않는다.** project-local constraint와 같은 계약, 같은 검증, 같은 등록
경로를 쓰며 frozen run input에서 구분되지 않는다(`UC-EXTENSION-003`).
"""
