# Handoff — Decision error contract, `strategy_manifest` 분할, capability protocol

이 문서는 다음 agent가 **이 대화를 읽지 않고** 작업을 이어받기 위한 것이다.
현재 상태, 다음에 무엇을 왜 해야 하는지, 그리고 내가 부딪힌 제약과 함정을 기록한다.

- **Branch**: `exp/one-shot` (base: `master`)
- **마지막 커밋**: `0e82254`
- **상태**: working tree clean, `132 passed / 1 failed`, `ruff check .` / `ruff format --check .` clean

> `1 failed`는 **기존부터 있던 것**이다. §5를 반드시 먼저 읽을 것.

---

## 0. 시작하기 전에 반드시 읽을 것

순서대로:

1. `AGENTS.md` — repository canonical 규칙. `CLAUDE.md`는 여기로 위임한다
2. `.agent/project.yaml` — 명령어와 canonical 문서 경로
3. `.agent/PLANS.md` — ExecPlan 표준. 큰 리팩터는 이걸 따른다
4. `docs/implementations/` 최근 3개 — 이번 3개 커밋의 설계 근거
5. `.agent/plans/active/` 2개 — 완료된 ExecPlan. 다음 작업 시작할 때 `completed/`로 옮길 것

검증 명령 (변경 후 반드시):

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
```

**중요한 repo 규칙 두 가지:**

- production source 동작을 바꾸면 `docs/implementations/`에 implementation record를 남긴다.
  문서·실험·showcase 전용 변경에는 만들지 않는다.
- 사용자가 명시적으로 지시하지 않는 한 stage/commit/push 하지 않는다.

---

## 1. 이번에 구현한 것 — 커밋 3개

| 커밋 | 내용 | record |
| --- | --- | --- |
| `f029253` | `strategy.py` 21곳 → 구조화 `QlibxError` (`QLIBX_DECISION_*` 18개 코드) | `decision-error-contract.md` |
| `40e6029` | `strategy_manifest.py` 1061줄 → package 6파일 | `strategy-manifest-package-split.md` |
| `0e82254` | capability 4벌 손코딩 → 공용 protocol | `capability-protocol.md` |

### 1.1 `QLIBX_DECISION_*` — 새 에러 네임스페이스

`strategy.py`(point-in-time decision 엔진)는 이제 bare `ValueError`/`RuntimeError`를
하나도 raise하지 않는다. `QLIBX_STRATEGY_*`는 **`strategy_manifest`가 소유**하므로 절대
섞지 말 것. 두 모듈은 다른 질문에 답한다:

- `QLIBX_STRATEGY_*` — manifest를 registered field에 대해 검증 (선언적 경로)
- `QLIBX_DECISION_*` — decision time의 point-in-time 경계 강제 (실행 경로)

가장 중요한 코드는 `QLIBX_DECISION_LOOK_AHEAD`다. `context`에 `boundary`
(`index` | `available_at`), `violation_count`, 그리고 실제로 경계를 넘은 관측 최대 5개를
싣는다. 위반을 **세기만 하고 지목하지 않으면** 호출자가 어느 row였는지 다시 유도해야 하고,
거기서 추측이 시작된다 — 이 설계 원칙을 유지할 것.

### 1.2 `strategy_manifest` package 구조

```
contracts.py    value object + manifest가 선언하는 requirements
loading.py      manifest/binding YAML → contracts
capability.py   project에 대한 evidence + read-only plan
resolution.py   승인된 binding → bounded pandas
invocation.py   신뢰 callable 로딩, 호출, Qlib execution adapter
```

**선언(`requirements()`)은 `capability.py`가 아니라 `contracts.py`에 있다.** 이유:
`cli.py:193`이 `manifest.requirements()`를 부르므로 dataclass에서 뗄 수 없고,
`_input_requirement`를 `capability.py`에 두면 순환이 닫힌다. 그런데 `_input_requirement`는
`qlibx.requirements`(layer 0)에만 의존하므로 애초에 `contracts.py` 소속이다. deferred import로
때우지 않았다. protocol 관점에서도 "capability가 무엇을 필요로 하는가"는 manifest에 내재하고,
"지금 project가 무엇을 공급하는가"는 evidence다.

### 1.3 Capability protocol

`qlibx/requirements.py`에 4개 추가. **이 모듈은 여전히 아무것도 import하지 않는다** —
pure domain package(`alpha`)에서 쓸 수 있어야 하기 때문이다. 깨뜨리지 말 것.

- `Finding` — probe의 답. **requirement/alternative ID를 갖지 않는다.** probe는 이미 둘 다
  받았으므로 되돌려주게 하면 bookkeeping 중복이 생긴다
- `gather_evidence(declaration, probe)` — 선언된 **모든 alternative**에 묻고 라벨링.
  `None` 반환은 거부가 아니라 기권
- `supplied_roles_probe(supplied)` — caller가 입력을 그냥 건네는 capability용 공용 규칙
- `plan_capability(...)` — gather → evaluate → plan

`RequirementEvidence`를 만드는 곳은 이제 패키지 전체에서 `gather_evidence` 한 군데다.

`profiles.py`만 `plan_capability`를 안 쓰고 2단계로 남겼다. warnings가 resolution 결과에
의존하기 때문이다. 이걸 억지로 흡수시키려고 `plan_capability`에 callable 파라미터를 추가하지 말 것 —
한 caller 때문에 공통 경로가 읽기 어려워진다.

---

## 2. 다음 작업 — 리뷰 우선순위대로

### 2.1 저장소 3개 → 1 store + 3 view (대)

`ArtifactStore`(`artifacts.py` 310줄) / `ResearchCatalog`(`research.py` 840줄) /
`RunCatalog`(`run_catalog.py` 13줄)가 각자 저장 관심사를 갖는다. 리뷰가 지목한 가장 큰 항목.

시작 전 확인할 것: `test_architecture.py`의 `LAYERS`에서 `artifacts`/`research`는 layer 4,
`run_catalog`는 layer 3이다. `run_catalog`가 `execution`과 함께 `_vendor` gateway
2개 중 하나라는 점(`VENDOR_GATEWAYS`)이 제약이다. `test_reporting_does_not_depend_on_the_execution_engine`이
왜 존재하는지 먼저 읽을 것 — reporting이 run catalog에 `execution`을 거쳐 닿으면 안 된다.

### 2.2 `research.py` (840줄) 협력 객체 분리 (중)

`structured-lookup-errors-and-boundary-cleanup.md`가 이미 예고했다:
"Splitting the event log, blob store, and publication protocol into separate collaborators
is the natural next step." `strategy_manifest` 분할과 같은 방식으로 하면 된다.

### 2.3 `documentation.py` (1213줄) package 승격 (소, 대부분 데이터)

`TOPICS` / `ERROR_GUIDANCE` / `SCHEMAS` / `EXAMPLES` 4개 mapping이 대부분이다.
`test_documentation.py::test_every_raised_error_code_has_installed_recovery_guidance`가
**양방향**으로 강제한다는 걸 잊지 말 것 (§4.1).

### 2.4 미구현 PRD 기능

- **Beta estimation / residualization** (PRD §8.2/§8.3) — requirement 기반은 준비됨, 의도적 연기
- `references/` target architecture 요소 (ComponentRef, FrozenInvocationBundle,
  TemporalSemantics, CostModelSnapshot, RiskModelSnapshot)
- Path B는 compatibility mode 유지 (의도된 한계)

### 2.5 `optimization.py` 22곳은 건드리지 말 것

순수 계산 함수의 인자 검증이고 `ValueError`가 맞다. 사용자가 명시적으로 제외했다.
전면 전환은 계약을 강화하는 게 아니라 희석시킨다.

---

## 3. 사용자 결정이 필요한 열린 항목 하나

**`require_ready` 추출이 layer 규칙에 막혀 있다.**

네 capability 모두 이렇게 끝난다:

```python
if not plan.ready:
    raise requirement_gap(plan.resolution.to_dict())
```

4벌 중복인데 추출하지 않았다. 공용 헬퍼는 `errors`와 `requirements`를 둘 다 봐야 하는데:

- `test_kernel_has_no_intra_package_dependencies` — 두 kernel 모듈이 서로 import 금지
- `test_alpha_is_a_pure_domain_package` — `alpha`는 `{errors, requirements}`만 의존 가능

**두 테스트 다 옳다.** 우회하면 사이트당 2줄 아끼자고 진짜 경계를 판다.
제대로 풀려면 "`alpha`가 layer-1 capability 모듈에 의존해도 되는가"를 사용자가 정해야 한다.
리팩터가 아니라 아키텍처 결정이다. **임의로 결정하지 말 것.**

---

## 4. 함정 — 내가 실제로 밟은 것들

### 4.1 documented ↔ raised 는 양방향 강제다

`test_documentation.py::test_every_raised_error_code_has_installed_recovery_guidance`는
AST로 `QlibxError(...)`/`unknown_name(...)`의 **첫 인자 리터럴**을 훑는다.

→ **code를 파라미터로 받는 helper에서 raise하면 스캔이 못 본다.** 나는 처음에
`_child_out_of_bounds(code, ...)`로 짰다가 두 코드가 "documented but unreachable"로 잡혔다.
해결은 코드를 하나로 합치고 `context["axis"]`로 나누는 것이었다. raise 지점을 리터럴로 유지할 것.

### 4.2 `QlibxError`는 `RuntimeError`다

`ValueError`를 잡던 곳이 조용히 안 잡게 된다. `strategy.py:393` `evaluate_child`가
정확히 그랬다 — 거부된 what-if가 답 대신 crash가 될 뻔했다. **`except ValueError`를 하는
호출자를 먼저 grep할 것.**

### 4.3 architecture 테스트는 package 승격을 견딘다 (설계된 것)

`test_architecture.py::_top_level()`이 package 디렉터리를 디렉터리 이름으로 매핑한다.
`strategy_manifest`를 package로 바꿨는데 테스트를 **한 줄도 안 고쳤고 그대로 green**이었다.
이게 핵심 신호다: 모듈 *파일* 기준으로 쓰인 테스트였다면 여기서 조용히 vacuous해졌을 것이다.
다음 분할(§2.1/§2.2/§2.3)에서도 테스트를 고쳐야 한다면 **분할이 틀렸는지 먼저 의심할 것.**

### 4.4 mutation 검증을 습관으로

새 assertion은 반드시 일부러 깨뜨려 확인했다. 특히 protocol에서:
`gather_evidence`가 `alternatives[:1]`만 돌게 해도 **실제 capability는 전부 통과한다** —
넷 중 셋이 requirement당 alternative를 하나만 선언하기 때문이다. fallback 경로는
`tests/test_requirements.py`의 `market_return` fixture에만 있다. 이 fixture를 지우지 말 것.

---

## 5. 알려진 실패 — 신규 아님

```
FAILED tests/acceptance/test_p0_p1_agent_journey.py::test_fresh_agent_onboarding_and_data_registration_journey
UnicodeDecodeError: 'cp949' codec can't decode byte 0xed in position 31
```

CLI subprocess 출력을 디코딩할 때 나는 **Windows 콘솔 코드페이지 문제**다.
`41f0928`(내 작업 이전)에서 stash 후 재실행해 baseline에서도 동일하게 실패함을 확인했다.
내 3개 커밋과 무관하다.

다만 **실제로 깨져 있는 테스트**이고 한국어 경로(`C:\Users\최재필\...`)를 쓰는 이 환경에서는
계속 재현된다. `tests/acceptance/test_p0_p1_agent_journey.py:34` 근처의 subprocess 캡처가
`encoding="utf-8"`을 명시하지 않는 것이 원인으로 보인다. 별도 작업으로 다룰 값어치가 있다.

**주의**: 앞으로 `pytest` 결과를 볼 때 기준선은 `132 passed, 1 failed`다.
`0 failed`를 기대하지 말고, `1 failed`가 **이것인지** 확인할 것.

---

## 6. 유지해야 할 설계 원칙

이번 3개 커밋을 관통하는 것들. 다음 작업에서도 지킬 것.

1. **위반은 세지 말고 지목한다.** `violation_count`만으로는 부족하고 `violations`에 실제
   레이블을 싣는다. agent가 다시 유도해야 하면 거기서 추측이 시작된다.
2. **비교가 이미 알고 있는 것을 버리지 않는다.** `_frames_equal_with_nan`은 어느 cell이
   다른지 계산해놓고 bool로 버리고 있었다. 지금은 `_frame_mismatch`가 그 이유를 반환한다.
3. **하나의 사실에 하나의 이름.** `provided_inputs`/`available_inputs`가 같은 사실을 두 이름으로
   보고하던 게 protocol 작업의 직접 동기였다.
4. **architecture 테스트가 막으면 우회하지 말고 보고한다.** §3이 그 예다.
5. **추상화가 evidence *결정*까지 삼키지 않게 한다.** protocol은 loop와 labelling만 갖는다.
   `plan_capability`에 caller 하나를 위한 flag를 추가하고 싶어지면 멈출 신호다.
