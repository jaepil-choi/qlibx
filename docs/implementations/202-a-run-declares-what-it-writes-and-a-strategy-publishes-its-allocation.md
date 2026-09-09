# 202 — A run declares what it writes, and a strategy publishes its allocation

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M2 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §2 (프로젝트는 그래프, run은 화살표) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `201` (run은 모델 하나) |

---

## 왜 이 변경이 있는가

PRD §2.8은 *"연구는 누적되어야 한다"*고 하고, 아키텍처 §1.1은 *"배분 결과가 dataset으로"* 되돌아오는
화살표를 그린다. 그런데 그 화살표는 **그림이었다.** 코드에서 dataset을 등록하는 run은 datamodel run
하나뿐이었고(`flow/datamodel/output.py`), strategy run의 배분 결과는 record의 `vqapr.weight`
테이블에만 남아 다른 run이 읽을 수 없었다. PRD §5.4의 *"StrategyModel이 StrategyModel의 결과를
구독한다"*는 그래서 별도 기능처럼 설명됐고, 실제로는 성립하지 않았다.

설계 §2가 세운 규칙은 이것이다:

> **run은 dataset 그래프의 화살표다. `reads`는 이미 선언한다; `writes`도 선언한다 — 필수로, 이름만.
> 선언한 것만 창고에 들어간다. 통장은 항상 생긴다.**

`writes`가 필수인 이유 셋은 설계 §2.1에 있다 — `reads`가 필수인데 `writes`가 선택이면 비대칭이고,
아무것도 안 만드는 run은 그래프의 규칙이 아니며, *"무엇을 만들려는가"*를 만들기 전에 말하게 하는 것은
연구 프레임워크에 기능이다. 이름을 돌리기 전에 짓게 되므로 *"돌리고 나서 이름을 붙이려면 다시 돌려야
한다"*는 문제가 발생할 수 없다.

---

## 무엇이 어떻게 바뀌었는가

### 선언

```
RunDefinition.writes: str                      필수.  두 kind 공통
DataModelEntry.dataset_id                      삭제 — run 의 writes 로 올라갔다
```

저장 spelling도 이 기회에 바꿨다 (record `201`이 미뤄 둔 것; 마이그레이션 한 번):

```yaml
# 이전                                  # 이후
strategies:                             writes: my-alpha-weights
  my-alpha:                             strategy:
    constraints: [no-short]               component: my-alpha
                                          constraints: [no-short]

datamodels:                             writes: momentum_20d
  momentum:                             datamodel:
    dataset_id: momentum_20d              component: momentum
    value_fields: [score]                 value_fields: [score]
```

**이전 spelling은 계속 읽힌다.** `_singular_block`이 `strategies:`/`datamodels:` 매핑을 받고, datamodel
엔트리 안의 `dataset_id`는 run 층 `writes`가 없을 때 그리로 끌어올린다. 2026-09-09 이전에 쓰인
워크스페이스는 그대로 열리고, 다음 쓰기에서 새 spelling으로 나간다 — `test_two_sections`가 은퇴한
섹션에 적용한 것과 같은 규율이다.

두 규칙이 선언에 추가됐다: `writes`는 `sessions_from`과 같을 수 없고(자기가 만들 dataset에서 세션을
가져올 수 없다), `execution.dataset`과도 같을 수 없다(자기가 만들 dataset에 대고 체결할 수 없다).

### 공개 경로가 하나가 됐다

`DataModelOutput`은 `FrozenDataModel`을 받아 `layer.dataset_id`와 `layer.value_fields`만 읽었다.
그 둘이 인자가 되면서 **`RunOutput`**이 됐다 — `RunOutput(root, writes=..., value_fields=...)`. datamodel
run은 전과 같이 세션마다 `append`하고 끝에 `register`한다. **strategy run이 같은 문으로 들어온다:**

```
_publish_allocation(root, frozen, result)
   vqapr.weight 의 행들  →  {available_at: event_time, instrument, weight: float}
                         →  RunOutput(writes=frozen.writes, value_fields=("weight",))
                         →  materialized/<writes>/  →  register(with_producer=run_id)
```

세 결정을 적어 둔다.

- **`available_at`은 recorder가 찍은 `event_time`이다.** 그 weight가 알려진 시각은 판단 시각이지 그
  전이 아니다. PIT 규칙은 datamodel 출력과 같다.
- **weight는 DOUBLE로 공개된다.** record에는 `str(Decimal)`로 정확히 남지만, 데이터 평면은
  *"kind당 숫자 타입 하나, DECIMAL은 의도적으로 부재"*다 (`docs/issues/archive/088`). 등록된
  벤치마크 비중과 공개된 배분이 **같은 종류의 입력**이 되는 것이 이 변환의 목적이고, 그것이
  `portfolio/allocation.py`가 주장하던 문장이다.
- **한 번도 판단하지 않은 전략은 아무것도 공개하지 않는다.** 빈 dataset은 타입을 가질 수 없고,
  타입 있는 무(無)는 거짓말이다. run은 완료되고, `writes`가 가리키는 dataset이 창고에 없다는 사실이
  `list runs` 옆의 `list datasets`에서 그대로 보인다.

### preflight와 judgments — 그래프의 첫 두 답

**충돌은 두 kind 공통이다.** `datamodel.output_registered`가 `run.output_registered`로 이름을 바꾸고
strategy run에도 묻는다. 예전엔 datamodel만 dataset을 썼으니 datamodel만 물었다.

**그리고 "남의 이름"과 "내 이전 산출물"을 가른다.** `show_001`이 이것을 드러냈다 — 같은 run을 두 번
돌리는 showcase(UC-TIME-002: 더 촘촘한 체결 테이블에도 같은 trace)가 두 번째 실행에서
`run.output_registered`에 걸렸다. 첫 실행이 `show001-weights`를 공개했기 때문이다. 그런데 그 dataset은
남의 것이 아니라 **이 run의 산출물**이고, 그것을 다시 만드는 것은 record를 다시 쓰는 것과 같은 종류의
결정이다. 규칙은 이렇게 섰다:

```
이름이 남의 것 (사람이 등록 / 다른 run 이 produced_by)   preflight · check 가 거절.  run.output_registered
이름이 내 이전 산출물 (produced_by == 이 run)             preflight · check 통과 — 선언의 결함이 아니라 상태
                                                          run():  replace_record 없음 → 계산 전 거절 (--force 안내)
                                                                  replace_record 있음 → 철회하고 다시 공개
```

`_own_output_or_refuse`가 `run()`에서 record의 `replace_record`와 **같은 플래그 아래** 그 결정을
내린다. 한 run이 자기 record와 자기 dataset을 다른 손잡이로 다루면 두 규칙이 어긋난다 — `--force`로
record는 갈아쓰고 dataset은 못 갈아쓰는 상태가 그것이다. `test_a_second_run_is_refused_before_it_computes`
가 이 세 갈래를 전부 고정한다.

**"없다"와 "아직 안 만들었다"를 가른다.** `_judge_member_datasets`가 미등록 dataset을 만나면
`workspace.producer_of(dataset_id)`를 묻는다 — 등록된 run 중 그 이름을 `writes`로 선언한 것이 있는가.
있으면 fix는 *"register it"*이 아니라 *"`vqapr run <producer>` first"*다. 이것이 설계 §2의 다섯
이득 중 첫째(*"준비 안 된 재료를 실행 전에 안다"*)이고, `get_close_matches`로 오타를 짚던 자리에
그래프의 답이 먼저 온다.

### 표면

```
vqapr run             envelope 에 writes
vqapr list runs       각 run 에 writes
vqapr rm run          두 kind 모두 writes 의 dataset 을 cascade 로 (참조되지 않을 때)
vqapr new             run 템플릿과 datamodel 스캐폴드가 새 spelling 을 emit
run.json              writes 필드
sample                strategy 가 <id>-weights 를 쓴다
skills                run-declaration.md 의 "One run, several strategies" 절이 정반대를 말하고
                      있었다 — 설계로 다시 썼다.  make-datamodel · make-constraint 의 spelling 갱신
```

---

## 무엇을 잃었나

- `DataModelEntry(component, dataset_id, value_fields)` 위치 인자 셋 → 둘. 호출자는 `writes=`를 run에
  둔다.
- `datamodel.output_registered` 코드가 은퇴하고 `run.output_registered`가 그 자리를 잇는다.
  characterization baseline은 `python -m tests.characterization.refusal_codes`로 재생성했고 diff는 그
  이름 하나다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **로더의 hoist가 매핑을 접었다.** 옛 spelling `datamodels: {a: {dataset_id: X, ...}}`를 읽을 때
  `dataset_id`를 run 층 `writes`로 끌어올리면서 매핑 전체를 그 한 엔트리로 바꿔 썼다 — 두 멤버를
  선언한 문서에서 둘째가 조용히 사라졌고, "정확히 하나"를 거절해야 할 자리가 통과했다.
  `test_a_run_writes_one_output_dataset`이 잡았다. 고친 모양은 `{**datamodel, name: entry}` —
  **바꾼 엔트리만 갈아 끼우고 나머지는 그대로 둔다.** 하위호환 로더가 "받아들인다"와 "잃어버린다"를
  구분하는지는 멤버 둘짜리 문서로만 확인된다.
- **shipped skill의 `.md`는 LF여야 한다.** Windows에서 `Path.write_text`로 스킬 문서를 고치면 CRLF가
  되고 `tests/skills`의 계약 테스트 7개가 해시 불일치로 떨어진다. `write_bytes`로 LF를 쓰고
  `scripts/record_shipped_skills.py`로 `_shipped.json`을 다시 기록한다.
- **`run()`은 워크스페이스를 한 번만 연다** (`docs/issues/archive/070`,
  `test_one_run_command_opens_the_workspace_document_once`). 자기-산출물 검사도 그 규율 아래
  있다: 호출자가 준 `Workspace`로 읽고, 없을 때만 열며, 문서가 **부재**면 검사할 것이 없으니
  통과한다 — `registered_roster`와 같은 좁은 관용이고 손상된 문서는 여전히 올린다. 그래서
  `roster._absent_workspace`가 `absent_workspace`로 공개됐다.

## 검증

```
uv run python -m pytest tests/ -q -m ""       1608 passed
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      67/81 changed → 원인 확인 후 다시 잡음 (아래) → 81/81
```

**digest 67건은 한 열이다.** run.json 12건과 datamodel.json 3건은 `writes` 필드다. 나머지 52건은
전략 record의 **모든 테이블**(`vqapr.account` · `vqapr.fill` · `vqapr.weight` · `alpha.signal` ·
`signal.measurement`)인데 행 수와 열이 같고 digest만 다르다. 모든 record 행이 `run_id` 열에
`FrozenRun.identity`(= run.json의 `declared_digest`)를 싣고, `writes`가 그 identity에 접힌다 —
*"다른 이름을 쓰는 두 run은 다른 run"*(frozen.py). 그래서 열 하나가 전부 움직였다. 시뮬레이션 값은
한 자리도 안 바뀌었고(첫 세 행의 weight·수량·현금이 M0 baseline 기록 시점의 showcase 문서와
일치), 기준선을 `--write`로 다시 잡았다. 기준선 diff는 정확히 그 67 entries다.

**showcase digest는 스위트와 동시에 돌리지 말 것.** `test_every_showcase_completes`가 같은
`outputs/`를 다시 쓴다. 처음 `--check`는 스위트와 겹쳐 파일이 사라졌다 나타났다 했고, 스위트가
끝난 뒤 두 번 돌려 같은 67건을 얻고서야 믿었다.

---

## 다음 기록이 이어받을 것

- `writes`가 run identity에 접히므로 **record의 모든 행이 바뀌었다**(`run_id` 열). 이 캠페인에서
  identity에 무엇을 더 접을 때마다(M4 agenda 어휘, M5 체결 어휘) 같은 67건이 다시 움직인다 — 그때는
  놀라지 말고 행·열이 같은지만 보고 다시 잡는다.
- 두 run이 같은 `writes`를 선언하는 것은 등록 시점에 거절되지 않는다 — 둘째가 preflight의
  `run.output_registered`에서 멈춘다. 등록 시점 거절이 더 나은지는 M2 밖.
- `RunOutput`은 여전히 `flow/datamodel/output.py`에 산다. 두 kind가 쓰므로 이름이 그 위치를 앞질렀다.
  Stage 5의 재배치 후보.
