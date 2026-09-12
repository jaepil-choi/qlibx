# 250 — A usage refusal names the form the command accepts, and what it refused

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-a-usage-refusal-names-only-vqapr-help-not-the-form-the-command-accepts.md` |
| **설계 근거** | 기록 `114`(usage 거절도 같은 봉투), `171`(stage `usage`, status 400) |
| **브랜치** | `develop` |
| **앞선 기록** | `114`, `171` |

---

## 왜 이 변경이 있는가

`vqapr new instruments A000020 A000030 --out i.yaml`과 `vqapr show strategy sample-run --strategy x`의 거절이
둘 다 `fix: "run \`vqapr --help\` to see the arguments this command accepts"`, `observed: "vqapr"`였다. argparse는
인식하지 못한 인자를 **최상위** parser에서 거절하므로 `prog`가 `vqapr`이고, `vqapr --help`는 하위 명령의
인자를 하나도 나열하지 않는다. 에이전트 다섯이 따로 만났고, 둘은 같은 거절에서 정반대 규칙을 적었다
("ids는 `--instruments`로" / "`--instruments`는 instruments scaffold에 안 먹는다") — 하나는 scaffold를 건너뛰고
`register_instruments`를 직접 불렀다.

## 무엇이 어떻게 바뀌었는가

- `cli/main.py`: `main`이 `parse_known_args`로 읽고, 남은 토큰은 `_Parser.reject_unrecognized`가 **그 토큰이
  따라온 하위 명령의 parser로** 거절한다. `build_parser`가 하위 parser를 `parser.commands`에 둔다. 하위
  parser 안에서 나는 거절(invalid choice, 필수 인자 없음)은 원래부터 그 parser의 `prog`였다.
- `cli/envelope.py::UsageError`가 `usage`(거절한 명령의 argparse usage 한 줄, 줄바꿈을 접은 것)와
  `observed`를 싣는다. `fix`는 `the form it accepts is \`<usage>\`; run \`vqapr new --help\` to see what each
  argument means`. `observed`는 인식 못 한 토큰 그대로, 그런 토큰이 없는 거절이면 친 명령줄.
- `--project-root`를 하위 명령 뒤에 둔 경우의 기존 문장 치환은 그대로(`_refusal` 한 자리).

## 바꾸지 않은 것

`code`(`usage.rejected`), `status` 400, `stage` `usage`, `requirement`(argparse 문구 그대로 — 두 번째 권위를
만들지 않는다는 기존 규칙). `--help`/`--version`의 경로.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_commands.py::test_an_unrecognized_argument_is_refused_by_the_command_it_followed` (신규) | 보고의 두 명령: `observed`가 `A000030` / `--strategy sample-reversal-5d`, `fix`가 `vqapr new --help` / `vqapr show --help`와 `--instruments`가 든 usage를 댄다; 파일은 안 써진다 |
| 같은 파일 `test_a_rejected_command_line_still_answers_in_the_envelope` | `observed`가 친 명령줄(`new bogus x`)을 담는다 — 단언 추가 |
| `tests/cli tests/qa tests/characterization tests/extension` 중 usage·envelope 관련 | 345 passed, 1 skipped (scaffold 변경과 함께 돈 묶음) |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
