# 243 — `dataset.unverified`가 그 dataset을 다시 측정하는 **있는** 명령을 말한다

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 하나를 닫는 bounded fix (0.14.2 hotfix) |
| **이슈** | `docs/issues/report-2026-09-10-unverified-fix-names-no-command-for-a-run-published-dataset` — 닫는다 |
| **설계 근거** | 기록 `234`(등록이 digest를 두고 이후는 identity 대조), run이 publish한 dataset은 `produced_by`를 안다(`project/document.py`), `tests/characterization/test_fix_is_not_a_restatement.py`(fix는 할 일을 말한다) |
| **브랜치** | `develop` (0.14.1 stamped 뒤) |
| **앞선 기록** | `234`, `242` |

---

## 왜 이 변경이 있는가

enhanced-index testbed(0.13.0 wheel)의 보고. 0.11.0 워크스페이스를 0.13.0으로 옮기며 0.12.0 마이그레이션
노트대로 선언 파일 셋을 `vqapr register`로 다시 등록했다. 다음 거절은 **선언 파일이 없는** dataset —
datamodel run이 `writes:`로 publish한 `alpha-beta-001-values` — 을 가리키며 이렇게 말했다:

```
dataset.unverified 412
observed: dataset 'alpha-beta-001-values' was registered before the measurement existed
fix:      register dataset 'alpha-beta-001-values' again
```

`vqapr register`는 선언 YAML이나 component `.py`만 받는다. run이 publish한 dataset에게 건넬 파일은 없다.
보고자는 그 명령이 존재하지 않음을 확인하는 데 반 시간을 쓴 뒤에야 되는 것 — 만든 run을 `--force`로 다시
돌리기 — 을 찾았고, 그것은 봉투도 마이그레이션 노트도 말하지 않았다.

`develop`(0.14.1)에서 그대로 재현된다: `data/validation.py::require_verified`의 두 거절(`dataset.unverified`,
`dataset.source_changed`)이 등록 주체를 묻지 않고 "register ... again"을 말한다. 등록 문서는 이미
`produced_by`를 든다(`list datasets`가 보여준다).

## 무엇이 어떻게 바뀌었는가

- `require_verified`의 두 거절이 `_measured_again(registration)`에서 **할 일과 명령**을 받는다.
  `produced_by`가 있으면 *"publish dataset 'X' again -- the command is `vqapr run <run-id> --force`"*,
  없으면 *"register dataset 'X' again -- the command is `vqapr register <its declaration file>`"*.
  `observed`도 run이 publish한 것이면 *"was published by run 'R' before the measurement existed"*라고 말한다.
  `retry_precondition`도 같은 명령을 든다.
- 코드·status·`key_path`·`source`는 그대로. 바뀐 것은 `observed`와 `fix`의 문장뿐이므로
  `tests/characterization/check_and_run_envelopes.baseline.json`을 그 의도로 재생성했다(한 줄:
  `sample-execution`의 `source_changed` fix).
- `docs/releases/0.12.0.md`의 마이그레이션 1항에 run이 publish한 dataset의 한 줄을 더했다: 만든 run을
  의존 순서대로 `--force`로 다시 돌린다.

**바꾸지 않은 것.** run이 publish한 dataset을 "다시 등록"하는 별도 명령을 만들지 않았다 — run이 그 등록의
문이고(`234`), 문을 하나 더 내는 것은 보고자가 청한 것도 아니다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/data/test_validation.py::test_a_run_published_registration_is_told_to_publish_again` (신규) | `with_producer("alpha-001", ...)`인 등록: `unverified`의 observed가 run을, fix와 retry_precondition이 `vqapr run alpha-001 --force`를 말하고 "register"를 말하지 않는다; `source_changed`도 같은 명령 |
| `tests/characterization/test_fix_is_not_a_restatement.py` | f-string fix가 literal 단어를 들도록 문장을 고친 뒤 통과(placeholder만 있는 fix는 "no substantive words"로 걸린다) |
| `tests/characterization` · `tests/data` · `tests/cli/test_check.py` | 통과 (0.14.2 노트의 `test_all`에 포함) |
| `ruff check src/` · `pyright` | clean · 0 errors |
