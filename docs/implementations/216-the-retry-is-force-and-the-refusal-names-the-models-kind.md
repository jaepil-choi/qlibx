# 216 — The retry is `--force`, and the refusal names the model's kind

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/090` — 문서가 말한 datamodel 재시도 절차가 바뀌지 않은 파일을 거절되게 두고, 그 거절이 datamodel을 strategy라 부른다 |
| **브랜치** | `develop` |
| **앞선 기록** | `215` · `171` (status가 누가 고쳐야 하는지를 말한다) · `148` (datamodel은 run이다) |

---

## 왜 이 변경이 있는가

`make-datamodel`의 `running-a-datamodel.md` "Retrying" 절은 `rm dataset` 뒤 `run`을 *the* 재시도
절차라고 썼다. 그것은 component 파일이 바뀐 경우에만 맞았다. 바뀌지 않은 파일이면 `rm dataset`은
성공해 출력을 지우고, `run`은 **다른** 거절 — `RunRecordExists`를 `InputError` 400
`argument.value_invalid`로 감싼 것 — 에 걸려 alpha가 dataset 없이 남았다. 그 거절의 모든 명사가
datamodel run에 대해 "strategy"라 말했고(`error`·`fix`·`retry_precondition`·`--force` help), 일상적
400에 `FileExistsError` traceback이 통째로 실려 왔다.

세 가지가 한 번에 틀렸다: 문서(절차와 code 이름 — `datamodel.output_registered`는 0.10.0에서
`run.output_registered`다), 분류(argument가 잘못된 게 아니라 store가 이미 가진 것과 어긋난 것,
즉 409), 명사(kind는 run이 안다).

## 무엇이 어떻게 바뀌었는가

- `cli/run.py` — `RunRecordExists`가 `_standing_record(existing, frozen, target)`로: **`record.exists`,
  409 `CONFLICT`, stage `record`**. `record.live`(423) 옆자리다. `frozen.datamodel`이 있으면
  "a datamodel record is written once per run and fingerprint", 없으면 strategy. `fix`는 "edit the
  {kind} … or replace this record and the dataset it published deliberately: `vqapr run <id> --force`".
  `cause`를 싣지 않는다 — OS의 `FileExistsError`는 record가 서 있음을 *발견한 방식*이지 독자가
  traceback을 봐야 할 것이 아니다. `raise … from None`.
- `--force` help — "replace this run's record (its strategy's or its datamodel's) … and the dataset
  it published".
- `running-a-datamodel.md` "Retrying" — **재시도는 `--force`다.** 두 거절(`run.output_registered`
  409, `record.exists` 409)을 이름 붙여 적고, `rm dataset`은 "버릴 출력을 지우는 것"으로 강등하고,
  그 사이의 빈 상태가 튜닝 루프에서 어디로 이어지는지(`091`) 한 문장.
- `run-backtest/references/records-and-tweaks.md`와 `introduce-vqapr/references/reading-the-envelope.md`의
  같은 절차·같은 옛 code 이름을 고쳤다.

## 대안과 트레이드오프

- **400 유지, 문구만 kind-aware로.** 기각: `report-issue-dev`의 결정표가 status로 갈리고, 409의
  정의("what is being registered or removed disagrees with what the workspace already holds")가
  이 상황 그 자체다. `record.live`가 이미 같은 이유로 `InputError`에서 `VqaprError`로 옮겨졌다(`171`).
- **`rm dataset`이 record도 함께 지우게.** 기각: 튜닝 워크플로우에서 record는 곧 이력이고(`090`의
  보고자가 `rm datamodel`을 우회책으로 쓰며 잃은 바로 그것), 지우는 verb 하나가 두 종류를 지우면
  `060`에서 배운 "무엇이 지워지는가를 이름으로 대라"를 어긴다.

## 검증

```
.venv/Scripts/python.exe -m pytest tests/cli/test_a_datamodel_run_through_the_cli.py tests/characterization -q
  통과 (새 단언: rm dataset 뒤 unchanged run → stage record · record.exists · 409 ·
        requirement가 "datamodel record" · fix에 --force · cause.traceback None; 그 뒤 --force 성공)
VQAPR_REGENERATE_REFUSAL_BASELINE=1 python -m tests.characterization.refusal_codes
  baseline에 record.exists (409) 추가
.venv/Scripts/ruff.exe check src/   All checks passed
```

`tests/cli/test_a_datamodel_run_through_the_cli.py::test_a_datamodel_run_is_registered_checked_run_listed_and_shown`
끝에 그 시퀀스를 붙였다.

## 남은 것

`rm dataset`이 남기는 "record는 있고 dataset은 없는" 상태 자체는 정당하다(버릴 출력을 지운 뒤
component를 고쳐 다시 돌리는 길). 그 상태를 `check`가 어떻게 보이는가는 `217`이 `run.output_stale`로
절반을 답한다 — dataset이 없으면 비교할 것이 없으므로 나머지 절반은 `run`의 409/`--force`가 답한다.
