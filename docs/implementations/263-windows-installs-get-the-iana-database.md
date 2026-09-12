# 263 — A Windows install gets the IANA time zone database, and a missing one is named

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-on-windows-a-strategy-naming-asia-seoul-fails-registration-as-a-502-blamed-on-user-code-until-tzdata-is-installed.md` |
| **브랜치** | `develop` |

---

## 왜 이 변경이 있는가

Windows의 새 uv 프로젝트에서 `uv add vqapr`만 한 뒤 `CalendarLookback(..., timezone="Asia/Seoul")`을 쓴 전략을 등록하면
502 `component.requirements_failed`, `origin: "user"`로 사용자 파일의 줄을 가리키며 거절됐다. 원인은 사용자 코드가 아니라
기계였다: Windows에는 IANA 데이터베이스가 없고, `tzdata` 패키지 없이는 `zoneinfo`가 어떤 zone도 모른다. 모든 KRX 예제의
zone이 그렇게 "모르는 zone"이 됐다. 에이전트는 스스로 진단해 `uv add tzdata`로 넘겼다.

## 무엇이 어떻게 바뀌었는가

- `pyproject.toml`: `"tzdata; sys_platform == 'win32'"`. 다른 OS는 시스템 데이터베이스가 답하므로 설치되지 않는다. lock에
  `tzdata`는 이미 있었고(dev의 pandas 경유) marker만 두 줄 더해졌다.
- zone을 이름으로 받는 세 곳(`domain/values.py`, `data/lookback.py::CalendarLookback`, `exchange/conventions.py::FillRule`)이
  각자 `ZoneInfo`를 부르고 각자 `unknown IANA timezone`을 쓰던 것을 문 하나 `domain/values.py::iana_zone`으로 모았다. 그
  문은 `available_timezones()`가 비었으면 — 이 Python이 데이터베이스를 하나도 못 찾으면 — "Windows는 데이터베이스를 싣지
  않는다; `tzdata`를 설치하라(`uv add tzdata`)"를 덧붙인다. 철자가 틀린 zone은 예전 문장 그대로다.

## 바꾸지 않은 것

철자 틀린 zone이 사용자 쪽 거절(502, 사용자 frame)인 것 — 그 zone 이름은 사용자가 썼다. 의존성이 생겼으니 데이터베이스
없는 Windows는 이제 깨진 환경에서만 나오고, 그때 문장이 원인을 말한다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/domain/test_an_unknown_zone_says_whose_it_is.py` (신규, 다섯) | `Asia/Seoul`이 풀린다; 철자 틀린 zone은 이름의 잘못; 데이터베이스가 없으면(`available_timezones` 비움) `uv add tzdata`를 말한다; `CalendarLookback`·`FillRule`이 같은 문으로 거절; `pyproject`가 win32에 `tzdata`를 선언 |
| `uv lock` | `tzdata` marker 두 줄 |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`, records `260`–`263` together) | 1788 passed, 1 skipped, 251.6 s |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
