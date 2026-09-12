# 220 — A missing source is a 404, and 502 is your code

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/094` — 두 거절이 `report-issue-dev`가 배정한 class 밖의 status를 단다 |
| **브랜치** | `develop` |
| **앞선 기록** | `219` · `171` (status는 누가 고쳐야 하는지를 말한다; `CRASHED = 502`의 정의) |

---

## 왜 이 변경이 있는가

`report-issue-dev`의 결정표는 `status`만으로 갈린다. 두 거절이 그 표의 class 밖에 떨어졌다.

1. **503 for a path that does not exist.** `extension/prepare.py::_unreadable`이 모든 `OSError`를
   `UNAVAILABLE`(503)로 묶었다. 503은 표에서 "retry the same command unchanged"인데, 없는 경로는
   재시도로 풀리지 않고 거절의 `retry_precondition` 자신이 편집을 요구했다. `Status.MISSING`의
   정의("or the path it names is not there")가 이 경우를 이미 담고 있다. **코드가 틀렸다.**
2. **502 for the author's own raise.** `Status.CRASHED = 502`의 정의는 "the user's own code raised
   while the framework was running it"이고 `status_of`는 innermost frame의 origin으로 500/502를
   가른다. 코드는 설계대로였다. 그런데 `report-issue-dev`의 표와 `what-counts-as-a-defect.md`("502
   upstream failure — vqapr failed to handle something a dependency did")와 skill 여덟 개의 footer가
   "500 or 502 is a vqapr defect"라 썼다. **문서가 틀렸다.** 표를 그대로 따르는 agent는 자기
   `AttributeError`를 결함으로 접수한다 — 보고자가 같은 세션에서 표를 신뢰해 자기 실수를 접수하지
   *않은* 결정을 했듯, 반대 방향으로도 표는 믿어진다.

## 무엇이 어떻게 바뀌었는가

코드(1):
- `extension/prepare.py` — `_unreadable`이 `FileNotFoundError | NotADirectoryError | IsADirectoryError`를
  **`component.source_missing`, 404**로 가른다. `fix`가 보고를 낳은 실수를 말한다: 상대 `path`는
  declaration 파일의 디렉터리 기준으로 풀린다. 나머지 `OSError`(권한, 디스크)는 503으로 남고 fix는
  "fix permissions"만 말한다.
- `extension/loading.py` — 로드 시점의 같은 두 raise 자리도 `_source_lost`로 같은 분할.

문서(2), 열 곳:
- `report-issue-dev/SKILL.md` — 표에 502 행을 따로: "**No** — your own component raised.
  `cause.origin` is `"user"` … Report only if `cause.origin` is not `"user"`, or the raise came from a
  package helper you called correctly". description의 "(status 500 or 502)"도 500만.
- `report-issue-dev/references/what-counts-as-a-defect.md` — 502 행을 "your code raised — you"로,
  503 행에 "a path that is not there is a 404"를.
- `analyze-result`·`inspect-workspace`·`make-compliance`·`make-datamodel`·`make-exchange`·
  `register-dataset`·`make-strategy`·`run-backtest`·`introduce-vqapr`(두 곳)의 footer — "500 is a
  vqapr defect; 502 is your own code raising (`cause.origin`, `cause.where`); 503 is the machine".

## 대안과 트레이드오프

- **502를 4xx로 옮긴다** (보고자의 1안). 기각: `171`이 5xx를 "the submission is fine; look at what
  ran — the user's code, the framework, the machine"으로 정의했고 502는 그 셋 중 첫째다. 코드가
  옳았고 표가 그것을 옮겨 적지 못했다. 표가 `cause.origin`도 보게 하는 것(보고자의 2안)은 사실상 이
  변경이다 — 502 행 자체가 origin을 읽으라고 말한다.
- **`OSError` 전부를 404로.** 기각: 권한 오류는 파일이 있는데 기계가 거절한 것이고, 그것은 503의
  정의다.

## 검증

```
.venv/Scripts/python.exe -m pytest tests/extension tests/characterization tests/agent -q
  통과 (새: tests/extension/test_strategy_registration.py::test_a_source_path_that_is_not_there_is_a_404_not_a_503
        — code component.source_missing, 404, fix에 "declaration file's own directory")
VQAPR_REGENERATE_REFUSAL_BASELINE=1 python -m tests.characterization.refusal_codes
  baseline: component.source_unreadable가 404 bucket에서 빠지고(prepare의 유일한 raise가 갈라졌으므로
  503만 남음) component.source_missing (404) 추가
.venv/Scripts/ruff.exe check src/   All checks passed
python scripts/record_shipped_skills.py            (0.11.0.dev0로 재기록)
python scripts/record_shipped_skills.py --check    exit 0
```

skill 파일은 `.gitattributes`가 LF를 강제하고 `test_the_shipped_bytes_do_not_depend_on_the_build_platform`이
그것을 지킨다 — 이 세션의 첫 편집이 CRLF를 넣어 그 테스트에 걸렸고, 바이트로 다시 썼다.

## 남은 것

- **후속(코드):** 패키지 helper의 typed refusal(`OptimizeRefusal` 등)이 사용자 callback 안에서 raise되면
  innermost frame이 패키지 것이라 500으로 분류된다. 그것은 결함이 아니라 입력 거절이므로 422
  (`CONTRACT`)에 `origin: "user"`가 맞다. 표의 502 행 마지막 절("a package helper you called
  correctly")이 그 틈을 임시로 덮는다.
- `Status.UNAVAILABLE`의 docstring("a file could not be read or written, a disk was full")은 그대로다
  — "없는 파일"은 이제 그 문장의 밖이다.
