# 262 — A declaration reads YAML 1.2's booleans, so `on: last` is the key `on`

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-the-run-template-shows-on-last-unquoted-and-uncommenting-it-makes-yaml-read-the-key-as-true.md` |
| **브랜치** | `develop` |
| **앞선 기록** | `253`(`agenda.on: last`) |

---

## 왜 이 변경이 있는가

demo testbed의 에이전트가 `vqapr new run` 템플릿에서 `# on: last`의 주석을 풀었더니 등록이 `agenda.1 Keys should be
strings [input_value=True]`로 거절됐다. PyYAML은 YAML 1.1을 따르고, 거기서 `on`·`off`·`yes`·`no`·`y`·`n`은 불리언이다. 그
키는 record `253`이 넣었고, 템플릿·run-backtest skill·0.14.4 릴리스 노트가 모두 따옴표 없이 쓴다.

## 무엇이 어떻게 바뀌었는가

템플릿 한 줄에 따옴표를 치는 대신 선언을 읽는 문 하나를 고쳤다. `domain/inputs.py::read_yaml_mapping`(사용자가 쓴 선언
YAML을 읽는 유일한 곳)이 `_DeclarationLoader`로 읽는다 — PyYAML의 safe loader에서 불리언 resolver만 YAML 1.2 core의 것
(`true`/`false`와 그 대소문자 변형)으로 바꾼 것. `on`, `yes`, `no` 같은 말은 어디에 있든 말로 읽힌다. 그래서 이미 나가 있는
문서의 `on: last`가 전부 그대로 맞는 말이 된다.

## 바꾸지 않은 것

`true`/`false`는 여전히 불리언이다. workspace 문서(`workspace.yaml`)는 우리가 쓰고 우리가 읽는다 — `SafeDumper`가 `'on'`을
따옴표로 쓰므로 그쪽 loader는 그대로 둔다(libyaml, 크기 때문에). 선언은 수십 줄이라 순수 Python loader로 충분하다.

## 트레이드오프

선언 어딘가에 `yes`/`no`를 불리언으로 쓴 사용자가 있다면 그 값은 이제 문자열이다. 선언 스키마에 불리언 필드가 그렇게
쓰일 곳은 없고(템플릿과 문서는 모두 `true`/`false`), 타입이 맞지 않으면 pydantic이 필드 이름으로 거절한다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_an_unquoted_on_is_a_key.py` (신규, 둘) | `on: last`·`off: 1`·`yes: no`는 말, `true`/`False`는 불리언; 샘플 프로젝트에 따옴표 없는 `on: last` 월말 run이 등록되고 `check`를 통과 |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`, records `260`–`263` together) | 1788 passed, 1 skipped, 251.6 s — every declaration the suite registers reads the same through the new loader |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
