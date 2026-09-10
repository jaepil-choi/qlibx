# 234 — A physical read is measured at one door, and verified by identity after

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-door 캠페인 V (`.agent/plans/active/one-door-campaign.md`) |
| **이슈** | `docs/issues/archive/095` — 닫는다 |
| **설계 근거** | 오너 지적 2026-09-10 "물리적 IO는 언제나 validate 하니까 validator가 따로 있어야" · `docs/issues/archive/023` (identity의 반쪽) · 0.11.0 척추 트레이스 `exp_230` `05_check_short` / `06_run_short` |
| **브랜치** | `redesign/one-door` |
| **앞선 기록** | `233` (The sample and the scaffolds compute on the matrix) |

---

## 왜 이 변경이 있는가

트레이스가 보인 것: 같은 집행표 parquet이 등록에서 한 번(`datasets.validate`, 네 단계), `check`에서
다시(`validate_execution_table` — 스키마·key·양수 가격, 각각 스캔), `run` preflight에서 세 번째,
`orchestration.run`에서 네 번째 스캔됐다. preflight의 key 스캔은 등록이 증명한 축을 다시 증명했고,
가격 스캔은 등록이 모든 후보 가격에 대해 한 번에 답할 수 있던 질문을 run이 고른 가격 하나에 대해
매번 물었다. roster는 세 번째 모양이었다: `read_roster_table`은 `Diagnosis` 없이 raise했다.

원칙은 어디에도 적혀 있지 않았다. 이제 적힌다 — **파일은 workspace에 들어오는 문에서 한 번 재고,
이후의 모든 읽기는 내용이 아니라 identity를 대조한다.**

## 무엇이 어떻게 바뀌었는가

```text
data/validation.py (new, 833)   verify_source(registration, spec) -> (Diagnosis, ValidationTiming, DatasetRegistration)
                                    schema → execution role → key → span → values → execution prices → digest
                                    돌려주는 등록은 span · source_digest · execution_prices를 든다
                                require_verified(registration, spec) -> DatasetRegistration
                                    digest 하나 대조, 스캔 0:  dataset.unverified (digest 없음, 234 이전 문서)
                                                              dataset.source_changed (바이트가 다르다)
                                verify_roster(tables) -> (Diagnosis, rows)   roster.table_missing · roster.table_invalid
                                check_schema/check_key/check_span/check_values/execution_role_failures  datasets.py에서 통째로 이사

data/datasets.py (1074 → 560)   선언 + 측정된 사실만. source_digest · execution_prices 필드, with_verification(), verified
data/sources.py                 physical_digest 가 여기 산다 (store.py도 여기서 가져간다)
project/document.py             codec: source_digest · execution_prices 직렬화 (없으면 None — 옛 문서는 열리고 목록되고, 읽으면 거절)
project/store.py                Workspace.require_verified(dataset_id) · Workspace.source_digest(source) — workspace 객체당 한 번 해시
project/merge.py                같은 선언으로 다시 등록하면 측정된 반쪽(span · aggregated · digest · prices)만 갈린다
flow/declaration/preflight.py   _validate_requirement · bound_execution_table 가 require_verified 를 부른다
                                execution.price_not_positive — run이 고른 가격이 등록의 execution_prices 에 없다
                                FrozenRun.source_digests — 얼릴 때 workspace가 이미 가진 digest
flow/orchestration.py           validate_execution_table 호출 삭제; _source_digests 는 frozen 것을 우선
exchange/execution_table.py     validate_execution_table · _schema_diagnosis · _key_diagnosis · _price_diagnosis 삭제
project/registration.py         verify_source · verify_roster (roster 실패는 InputError 로 감싼다)
flow/run/output.py · flow/roster.py · cli/list_.py   같은 문
```

- **집행 가격은 등록에서 모든 후보에 대해 한 번 잰다.** `execution_prices`는 tradable 행마다 유한하고
  양수인 숫자 필드의 이름들이다. run이 `trade_price: close`를 고르면 preflight는 그 이름이 그 튜플에
  있는지 본다 — 스캔이 아니라 튜플 조회. 옛 `execution_table.price_invalid`는 등록 시점의 측정 +
  preflight의 `execution.price_not_positive`가 됐다.
- **preflight의 key 스캔은 사실을 잃지 않고 사라졌다.** 집행표의 `(trade_at, instrument)`는 dataset의
  `instrument_instant` key이고, 등록이 그것을 증명했다(`dataset.key_duplicate`).
- **다시 등록하는 것이 수리다.** `dataset.source_changed`의 fix는 "register again"인데, 옛 merge 규칙은
  측정된 span이 다르면 `dataset.registered`로 거절했다 — 그 fix는 되지 않는 명령이었다. 이제
  `project/merge.py`는 선언된 반쪽이 같으면 측정된 반쪽을 갈아 끼운다. 234 이전 문서(digest 없음)도
  같은 길로 수리된다. 선언이 다르면 여전히 `dataset.registered`.
- **roster 읽기는 `Diagnosis`다.** `verify_roster`는 없는 표·못 읽는 표를 코드로 돌려주고, 등록은 그것을
  기존처럼 `InputError`로 감싼다(코드는 그대로 `VALUE_INVALID`).
- **`Workspace.require_verified`는 workspace 객체당 source 하나를 한 번 해시한다.** `check`가 judgments와
  preflight에서 같은 표를 두 번 물어도 sha256은 한 번이다.
- **문을 지키는 테스트 둘.** `tests/boundaries/test_physical_reads_pass_one_door.py`는 AST로 `scan.describe
  · describe_projection · key_check · span_check · finite_check · positive_finite_when_true`를 부르는 모듈이
  `data/validation.py` 하나뿐임을(그리고 그 문이 여섯을 다 씀을) 잡는다. `tests/cli/test_check.py::
  test_check_reads_no_file_content`는 `check` 한 번 동안 커널 호출이 0임을 센다.
- `cli/list_.py`의 함수 안 import 둘이 모듈 위로 올라갔다(순환이 없었다). deferred import 천장 10 → 9.

**하지 않은 것.** `datasets.py`의 선언 파서(`parse_grain`, `parse_field_types`)는 그대로다 — 선언의
자리다. `extension/conformance.py`(컴포넌트 소스의 검사)는 물리 *데이터* 읽기가 아니라 코드 로드이고,
`Diagnosis`를 이미 돌려주므로 이 문 밖에 둔다. 옛 문서의 자동 마이그레이션은 없다: `grain`·`field_types`
때와 같이, 읽는 쪽이 이름으로 거절하고 `register`가 고친다.

## 성능

sample door 프로젝트(10종목 · 6,902행 집행표, `scratchpad` smoke): `vqapr check sample-run` 벽시계
1.37 / 1.44 / 1.38 s, 그중 CLI 기동(`vqapr --help`) 0.91 s. 트레이스 `05_check_short`의 11.8 s는
프로파일러 아래의 3,000종목 표라 직접 비교 대상이 아니다; 비교 가능한 사실은 `check`가 이제 집행표의
내용을 읽지 않는다는 테스트다(위).

## 검증

| 검사 | 결과 |
|---|---|
| smoke journey (sample door 프로젝트) | register → `workspace.yaml`에 `source_digest`·`execution_prices`; check ok; run 완료; 집행표를 줄인 뒤 check → `dataset.source_changed`; 같은 선언으로 register → 통과, check ok |
| `tests/characterization/refusal_codes` | 기준선 재기록: + `dataset.execution_instrument_not_text` · `dataset.unverified` · `dataset.source_changed` · `execution.price_not_positive` · `roster.table_missing` · `roster.table_invalid`; − `execution_table.*` 다섯 |
| fast suite | 1685 passed, 29 deselected (1672 → +13: 문의 테스트 8, 집행 입력 3 재작성, check 스캔 0, 경계 2 — 삭제된 `validate_execution_table` 테스트만큼 빠짐) |
| digest | 83/83 |
| ruff (src) · pyright (src) | clean · 0 |
