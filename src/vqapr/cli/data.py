"""`vqapr data ...` — dataset 등록과 조회, 그리고 calendar 유도.

구현할 것
    register   SourceSpec + DatasetRegistration을 검증하고 workspace에 기록
    inspect    등록된 dataset의 binding, coverage, available_at 규칙을 보여준다
    calendar   등록된 dataset에서 frozen SessionCalendar를 유도해 workspace에 기록

**agent user가 이 package로 가장 먼저 하는 일이 여기 있다.**
    그래서 등록 실패가 `domain/errors.py`의 machine-readable 계약을 처음으로 시험하는 자리다.

register가 하는 일 넷
    1. 물리 선언   SourceSpec — 이 경로에 이렇게 쌓여 있다
    2. 의미 선언   DatasetRegistration — 이 값이 무엇이고 언제부터 볼 수 있나
    3. 검증        `data/scan.py`로 실제 파일을 열어
                      선언한 컬럼이 존재하나
                      (available_at, instrument)가 null 없이 유일한가
                      availability 규칙이 tz-aware 시각을 만드나
                      날짜 컬럼이 실제로 date로 파싱되나
    4. 기록        검증된 선언을 workspace에 (`workspace.py`)

calendar가 여기 있는 이유
    calendar는 별도 파일에서 오지 않고 **이미 등록한 dataset에서 나온다**(§3.6). 일별 시세를
    등록했다면 그 dataset이 곧 원천이다.

        vqapr data calendar --from price_daily
                            --rule all-instrument-date-union
                            --session-close "15:30 Asia/Seoul"

    이 명령이 dataset에서 distinct 날짜를 읽어(`data/scan.py`) 규칙에 넘기고
    (`runtime/calendar_derivation.py`), 결과 frozen calendar를 workspace에 남긴다.

    **시각은 유도되지 않는다.** `--session-close`가 필요하며 등록의 available_at 규칙을 재사용할 수
    있다.

여기서 하지 않을 것
    **availability를 추측하지 않는다.** 날짜 컬럼을 자동으로 00:00으로 해석하지 않으며, 근거가
    확인되기 전에는 `available_at`으로 간주해 등록하지 않는다. 후보를 제시하는 것은 agent의 일이다
    (`UC-AGENT-001`).

    **calendar를 추측하지 않는다.** 규칙을 고르지 않으면 calendar가 생기지 않는다.

    등록된 값이 point-in-time으로 안전한지 판정하지 않는다. 보장하는 것은 **선언된 availability의
    준수**뿐이다(PRD §3.2).

    **user에게 질문하지 않는다.** 인자를 받아 판정 결과를 낸다. 대화는 agent skill이 담당한다.
"""
