# 개념 트리 캠페인 — 폴더가 고리의 개념을 따르고, 저자의 표면은 하나, 루프는 DES의 말을 쓴다

**2026-09-11 ~ 2026-09-12 · branch `redesign/concept-tree` · records `268`–`279` · 0.16.0 · 완료.**

## 왜

오너의 질문은 이랬다. "데이터가 들어오면 전략이 판단하고, exchange가 체결하고, 다시 전략으로 넘겨주는 게 끝인데, 왜
`src/`가 이렇게 복잡하지?" 읽어 보니 고리는 단순했다. 복잡했던 것은 폴더였다. 폴더는 개념이 아니라 import 높이로
나뉘어 있었다.

- Account 하나가 여덟 파일에 흩어져 있었다.
- 같은 파일 이름이 아홉 쌍이었다(`store.py` 둘, `document.py` 둘, `run.py` 둘 …).
- 역할을 부르는 열거가 둘이었다(`Role` · `ComponentKind`).
- Call들에 공통 base가 없었다.
- base class가 구현과 한 파일에 있었다(`exchange/venue.py`에 base와 `AcademicExchange`).
- `analysis`와 `report`가 같은 일을 했다.

## 오너 판정 (2026-09-11 ~ 12)

- `domain/`은 DDD의 뜻으로 평평하게 둔다. 이름은 실제 OOP · DDD · 설계 용어로 짓고, base는 구현과 파일을 나눈다.
  폴더는 Component 추상화를 이어 간다.
- 루프는 EDA가 아니라 DES다. `agenda`와 `occurrence`는 어휘에서 빼고 `schedule` · `event`를 쓴다. `signals/`와
  `portfolio/`는 주제 패키지로 둔다.
- 계좌는 자기 보유를 스스로 곱하고, 가격 고르기만 `domain/valuation.py`에 남긴다.
- CLI는 `public`과 application layer만 import한다. `public`이 유일한 저자 표면이다(`vqapr.authoring` 삭제).
- M2–M10은 쭉 진행하고 M11 앞에서 멈춘다. M11은 전부 재등록을 요구한다(옛 `agenda:`는 어디서든 거절). 옛 run 기록은
  거절하고 다시 run 하라고 말한다(A).
- 새로 지은 이름을 승인했다: `registry` · `verdict` · `assemble` · `batch` · `recording` · `compose` · `netting` ·
  `Clock.SCHEDULE`.

## 한 것

| record | 한 문장 | 비유 |
|---|---|---|
| `268` | `domain/`: 개념 하나에 모듈 하나(account · fill · order · intent · listing · cost · valuation …) | 서랍마다 한 가지 물건만 넣고 서랍에 그 이름을 쓴다 |
| `269` | `data/`가 모든 읽기를, `record/`가 표 이름을 가진다 | 창고의 입구와 출고 대장을 한 벽에 |
| `270` | `signals/` · `portfolio/`는 주제로 가른 두 패키지 | "순수 함수" 서랍 대신 "신호" 서랍과 "포트폴리오" 서랍 |
| `271` | `component/`: 역할마다 모듈 하나, base는 구현과 다른 파일 | 계약서와 견본품을 한 봉투에 넣지 않는다 |
| `272` | 역할의 이름은 `Role` 하나, 네 Call에 base 하나 | 같은 사람을 두 이름으로 부르지 않는다 |
| `273` | `project/` → `workspace/` (`registry` · `declarations` · `run_definition`) | 폴더 이름을 사용자가 부르는 이름으로 |
| `274` | `flow/` → `run/`: 출발 전(preflight) · 고리(engine, 단계는 부르는 메서드 이름) · 조립 | 비행의 출발 전 점검 · 운항 · 착륙 뒤 기록 |
| `275` | `analysis/`를 `report/`에 합침(`metrics` · `compose`), 보고서의 `Series`는 `Curve` | 계산하는 사람과 보고서 쓰는 사람이 같은 사람이었다 |
| `276` | 계좌가 자기 보유를 곱하고, valuation은 가격만 고른다 | 장부 주인이 자기 장부를 계산한다 |
| `277` | CLI는 표면으로만 읽고, 파일 이름은 한 뜻(`base.py`만 예외) | 손님은 계산대로만, 이름표는 하나씩 |
| `278` | 루프의 어휘: `schedule` · `ScheduledEvent` · `Clock.SCHEDULE` · `event_id` · `call.at`, 옛 기록은 다시 run | 시간표가 사건을 만든다 |
| `279` | 저자의 표면은 `vqapr.public` 하나(`from vqapr import public as vq`), `preflight` · `freeze` | 정문 하나 |

## 목표 문서와 다르게 둔 것

모두 문서와 계획에 적었다.

- `domain/cost.py`를 따로 둔다. 합치면 fill → order → listing → fill 순환이 생긴다.
- compliance의 판정 값은 `component/compliance/report.py`에, 루프의 사건은 `run/engine/events.py`에 둔다. 목표
  대응표에 숨어 있던 순환 둘이다.
- `run/preflight/frozen.py`를 `freeze.py` 옆에 따로 둔다. 풀리지 않는 체결 목표는 `facts.py`에 둔다.
- scaffold는 `agent/scaffold.py`에 둔다(AC4).
- `AccountMark.provenance`를 삭제했다. 아무도 읽지 않았다.

## 하지 않은 것

- Accrual의 구현(배당 · 쿠폰 · 이자 · 펀딩비). 자리와 배선만 있다.
- `ModelWindow.evaluation_time` · `ScheduledEvent.evaluation_time`의 이름. 저자에게 보이는 시각은 `call.at` 하나다.
- `experiments/`와 옛 문서(`docs/implementations` · `docs/issues` · `docs/archive`). 측정한 버전의 경로를 그대로 둔다.

## 사고 한 건

M7에서 스크립트가 실패한 뒤, 같은 줄의 `rm -rf`가 옮기지 않은 `flow/`를 지웠다. 스테이징 전이었으므로
`git checkout --`으로 52개 파일을 모두 되살렸다. 이후 정리는 스크립트가 성공했을 때만 돈다.

## 검증

M2–M10은 매 단계 `test_all` · showcase digest(캠페인 기준선 81개가 매번 똑같음) · ruff · pyright를 거쳤다.
M11–M12와 릴리스의 수치는 `docs/releases/0.16.0.md`의 Validation에 있다.
