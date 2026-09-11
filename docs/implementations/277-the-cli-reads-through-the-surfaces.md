# 277 — CLI는 표면으로만 읽고, 모듈 이름은 하나를 뜻한다

| | |
|---|---|
| **작성 시각** | 2026-09-12 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M10 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §14 · §15, 수용 기준 AC3 · AC4 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `271`–`276` |

---

## 왜 이 변경이 있는가

오너가 정한 규칙은 이렇다. "CLI는 public과 application layer만 import하고, public이 저자의 유일한 표면이다."
M9까지 옮기고 보니 CLI가 표면을 지나쳐 안쪽으로 손을 뻗는 곳이 네 군데 남아 있었다.

- `list components` · `show model`: `component.loading`의 로더를 역할별로 직접 골라 불렀다.
- `list instruments`: `data.verification.verify_roster` → `diagnosis.raise_if_failed()` → `build_roster`를 직접
  이었다. run이 roster를 읽는 `run/roster.py`와 **똑같은 세 줄**이었다.
- `show dataset`: `data.scan`의 projection · head · row count를 CLI 안에서 조립했다.
- `new`: `component.scaffold`에서 비공개 `_class_name`까지 가져왔다.

규칙을 지키는 방법은 두 가지다. 표면을 넓히거나, 그 일을 맡을 application layer의 문을 만드는 것이다. 이번에는 문을
만들었다. 이 조각들은 저자가 쓸 도구가 아니라 CLI의 verb가 하는 일이기 때문이다.

## 무엇이 어떻게 바뀌었는가

| CLI가 쓰던 것 | 이제 지나는 문 |
|---|---|
| 역할별 로더 셋 | `workspace/registry.py::load_registered(ref)` — workspace가 등록한 것을 그 역할의 로더로 되살린다. run의 preflight가 쓰는 로더와 같다 |
| roster 검증 + 조립 | `run/roster.py::read_roster_tables(tables)` — roster를 읽는 두 곳(run은 거절하고, `list`는 `unreadable`로 알린다)의 한 문. 중복 세 줄이 하나가 됐다 |
| scan 조립 | `workspace/preview.py::preview_dataset` — 등록된 dataset을 어느 scan이 답하는지는 등록을 가진 workspace가 정한다 |
| `component/scaffold.py` | `agent/scaffold.py` (`_class_name` → `class_name_for`) |
| `Role` · `AccountMode` · `InstrumentKind` · `StrategyModel` · `build_roster` | `vqapr.public` (이미 공개된 이름) |

- **scaffold가 `agent/`로 간 이유 (목표 트리와 다르다).** `vqapr new`만 scaffold를 읽는다. `public`으로 보내면
  두 길밖에 없다. 템플릿 도우미 셋을 저자 표면에 더하거나, 하나로 합쳐 `new`의 거절 순서를 바꾸는 것이다(지금은
  id를 `--dataset`보다 먼저 본다). `agent/`는 스킬과 sample 전략이 있는 application layer의 저작 보조 패키지다.
  템플릿은 그 옆에 둔다. `component/`는 계약 · 출하 구현 · 들어오는 문(reference · fingerprint · loading ·
  conformance)만 가진다. scaffold만 다루는 테스트 셋은 `tests/agent/`로 옮겼다.
- **AC4 테스트** `tests/boundaries/test_the_cli_reads_through_the_surfaces.py`: `cli/*.py`의 import를 AST로 모두
  읽는다(함수 안 import도 포함). 허용하는 것은 `public` · `workspace` · `run` · `record` · `report` · `agent` ·
  `domain.errors` · `cli`뿐이다.
- **AC3 테스트** `tests/boundaries/test_a_module_name_says_one_thing.py`: 패키지 안에 같은 파일 이름이 둘이면
  실패한다. `base.py`만 예외다. 반복되어도 늘 "이 패키지의 base"라는 한 뜻이기 때문이다.
- **ruff `A005`**(표준 라이브러리 모듈 이름을 가리는 모듈)를 켰다. 이미 통과한다. `signals`를 복수로 지은 이유가
  이제 규칙이 됐다.
- **두 기존 판결을 함께 고쳤다.** facade tripwire(`test_the_facade_is_not_reached_up_to`)의 바닥이 3에서 6이 됐다. CLI verb
  셋이 facade를 쓰는 것은 그 판결이 말한 "CLI 자신"의 쓰임이다. 테스트가 요구한 대로
  `docs/design/agent-first-surface.md`에 AC4 부록을 달았다. `cli/new.py`는 이제 facade를 실제로 import하므로
  "템플릿 글자는 세지 않는다"는 고정에서 빠졌다. 함수 안 import의 상한(`CEILING`)은 9에서 7로 내렸다. `show.py`의
  함수 안 로더 import 둘이 사라졌기 때문이다.
- **층 번호의 최종값.** `workspace` 30 · `run.preflight` 40 · `run.engine` 45 · `run` 50 · `report` 60.
  `component` 20과 과도기 `authoring` 21은 그대로이고, `authoring`은 M11에서 사라진다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1797 통과 · 5 skip (212 s). 새 guard 테스트 둘을 더했고, facade 템플릿 고정에서 매개변수 하나(`cli/new.py`)가 빠졌다 |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 (`A005` 포함) |
| `uv run pyright` | 0 errors, 0 warnings |
