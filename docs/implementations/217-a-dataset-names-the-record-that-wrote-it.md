# 217 — A dataset names the record that wrote it, and `check` compares

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/091` — materialized dataset이 자기를 만든 component fingerprint를 기록하지 않는다 |
| **브랜치** | `develop` |
| **앞선 기록** | `216` · `160` (dataset의 `produced_by`) · `148` (`_judge_outputs`) |

---

## 왜 이 변경이 있는가

`produced_by`는 run id만 담았다(`160`). 같은 run id 아래 record는 fingerprint별로 쌓이는데
(`<id>@<fp8>`), 그 record들이 전부 같은 dataset id를 썼다고 주장하고 parquet은 하나뿐이면, dataset은
N개 버전 중 어느 것을 들고 있는지 말하지 못했다. testbed의 sweep은 파일을 best 버전으로 되돌린 뒤
dataset 디렉터리가 있다는 이유로 다시 돌리지 않았고, 8개 중 5개 alpha의 parquet이 **마지막으로
시도한 값**의 것이었다 — `peer_009`의 Sharpe 0.82 대 0.17, 오류도 없고 확인할 field도 없이. 재실행
자체는 0.10.0에서 이미 안전하다(`--force` 없는 재실행은 409). 위험은 **재실행을 하지 않은 상태**에
있었고, 그것은 dataset이 자기 버전을 말하지 않는 한 어느 verb도 볼 수 없었다.

## 무엇이 어떻게 바뀌었는가

**`produced_by_record`** — dataset 등록의 새 측정 필드. `<component_id>@<fp8>`, `list datamodels`와
`rm datamodel`이 record를 지목하는 바로 그 ref.

- `data/datasets.py` — `DatasetRegistration.produced_by_record`; `with_producer(run_id, record_ref=None)`이
  둘을 함께 붙인다. `record_ref`는 옛 문서(필드가 없던 때 쓴 것)를 위해서만 optional이다.
- `project/document.py` — codec 필드, 측정값 목록(없으면 문서에 쓰지 않음), to/from_domain.
- `flow/run/output.py` — `RunOutput(record_ref=…)`; `register`가 `with_producer(run_id, record_ref)`.
- `flow/orchestration.py` — datamodel run은 `layer.record_ref`, strategy의 allocation 발행은
  `frozen.strategy.record_ref`를 넘긴다. 두 kind가 같은 문으로 나가니 둘 다 자기 버전을 말한다.
- `cli/show.py`·`cli/list_.py` — `show dataset`·`list datasets`가 필드를 보인다.
- `flow/declaration/judgments.py` — **`run.output_stale`, 412.** `_judge_outputs`가 "이 run 자신의
  출력"인 경우 `_judge_output_freshness`로 넘어가, dataset의 `produced_by_record`와 지금 등록된
  component의 `<id>@<fp8>`을 비교한다. 다르면 두 ref를 `observed`에 대고 fix는
  `vqapr run <id> --force`. component가 resolve되지 않으면 조용히 통과한다(member judge가 그것을 보고한다);
  옛 문서라 `produced_by_record`가 없으면 비교할 것이 없다.
- **`run`의 문에서는 묻지 않는다.** `require_judged`가 `RUN_OUTPUT_STALE`을 걸러낸다: `--force` 없는
  `run`은 자기 출력을 어차피 409로 거절하고, `--force`는 그 판정이 이름 댄 바로 그 수리다. 판정을
  `run`에도 올리면 수리하는 명령을 거절하게 된다 — 처음 구현이 정확히 그렇게 실패했고
  (`run alpha --force`가 412로), 그래서 이 예외를 docstring에 적었다.

문서: `inspect-workspace/SKILL.md`, `make-datamodel`의 `running-a-datamodel.md`("Counting runs":
"existence of the directory is not identity of its contents")와 `output-schema.md`.

## 대안과 트레이드오프

- **`produced_by`를 record ref로 바꾼다** (보고자의 1안). 기각: preflight·orchestration·judgments 세
  곳이 `produced_by == run_id`로 "이 run 자신의 출력인가"를 판정한다. 필드를 하나 더하는 쪽이 그
  비교를 건드리지 않는다.
- **`run`이 fingerprint가 다른 기존 dataset을 거절한다** (보고자의 3안). 이미 그렇다 — 0.10.0의
  `run.output_registered`가 `--force` 없는 모든 재실행을 거절한다. 문제는 실행이 아니라 부재였다.
- **stale을 `run`에서도 거절.** 위에 적은 대로 `--force`와 모순된다.

## 검증

```
.venv/Scripts/python.exe -m pytest tests/cli/test_register_says_what_a_declaration_means_and_a_dataset_names_its_producer.py tests/characterization -q
  통과 (새: produced_by_record == list datamodels의 datamodel_ref; strategy run의 own file은 None;
        component 편집·재등록 뒤 check → run.output_stale 412, observed에 옛 ref, fix에 --force;
        run --force 뒤 check 통과, produced_by_record가 바뀜)
VQAPR_REGENERATE_REFUSAL_BASELINE=1 python -m tests.characterization.refusal_codes
  baseline에 run.output_stale (412) 추가
.venv/Scripts/ruff.exe check src/   All checks passed
```

## 남은 것

- 옛 문서의 dataset(`produced_by`만 있고 `produced_by_record` 없음)은 stale 판정을 받지 않는다. 한 번
  `--force`로 다시 쓰면 붙는다. 0.11.0 노트에 적었다.
- strategy run의 allocation dataset도 `produced_by_record`를 갖지만, strategy run은 `writes`를 자기
  출력으로 다시 쓰는 흐름이 datamodel과 같아 별도 판정은 두지 않았다 — 같은 `_judge_outputs`가 둘 다
  본다.
