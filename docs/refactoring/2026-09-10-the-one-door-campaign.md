# 한 문 캠페인 — 루프 클래스 하나, panel 블록 하나, 검증 문 하나

0.11.0의 척추 트레이스(`experiments/exp_230_the_spine_trace/`, `sys.setprofile`로 sample door를
따라간 열 장면)를 읽으며 오너가 정확하지만 틀린 것 셋을 찾았다.

- **`097`** — `flow/engine/loop.py`의 추상 `EventLoop`에 서브클래스가 `RunLoop` 하나뿐이다.
  `StrategyEventLoop`·`DataModelEventLoop`는 `__init__`만 있는 클래스다.
- **`096`** — panel 읽기가 종목 순회 Python 루프라서 sample 전략도 `for name in window.instruments`를
  돈다. "5일 close lookback 받은 2d panel을 가지고 axis=0으로 mean 해주고 부호만 −로 해주면 되잖아."
- **`095`** — 물리 읽기의 검증에 문이 하나가 아니다. `datasets.validate`, `validate_execution_table`,
  `read_roster_table`이 각자의 모양이고, 같은 집행표가 등록·check·preflight·run에서 네 번 스캔된다.

브랜치 `redesign/one-door`, develop `68ff73f9`(record `230`)에서 시작. 마일스톤마다 기록 하나, digest
게이트(`scripts/showcase_record_digest.py --check`, 83 entries)는 내내 유지. 계획 원본은
`.agent/plans/` (로컬)이고 이 문서는 그 결산이다.

## 0. 소유자 결정 (2026-09-10)

1. **stepper보다 고치는 것이 먼저다.** 루프도, decide의 for loop도, 흩어진 validate도. 각 항목에 이슈를
   먼저 등록하고 clean code · architecture로 고칠 전체 계획을 낸 뒤 착수.
2. **순서 L → P → V.** L은 둘 다 그 위에 올라설 작은 절단; P는 sample fingerprint를 바꾸므로 한 단위로;
   V는 저장 문서의 모양을 바꾸는 가장 큰 것이라 마지막.
3. **0.12.0.** V가 workspace 문서의 모양을 바꾸므로(그 전에 쓴 등록은 다시 등록해야 읽힌다) breaking.
4. **stepper는 10종목이면 충분하다.** 흐름을 보려는 것이지 성능을 보려는 것이 아니다. 캠페인이 끝난 뒤
   여섯 시나리오(데이터 등록 / 등록 오류 / DataModel → firm characteristics / factor 전략 /
   memory를 쓰는 stop-loss / 저장된 alpha로 enhanced index)를 고쳐진 API 위에서 실제 트레이스로 쓴다.

## 1. 마일스톤과 기록

| 마일스톤 | 기록 | 무엇이 바뀌었나 | 게이트 |
|---|---|---|---|
| M0 | — | 기준선: fast 1671, digest 83/83, pyright 0; `exp_221` 3,000×1일 38.7/35.5 s; `exp_231` sample decide 8.8 ms · counts 3.1 · block 0.1 | — |
| L | `231` | `EventLoop` 삭제, `RunLoop.run`이 걷기; `strategy_loop`/`datamodel_loop`는 `RunLoop`를 돌려주는 함수; `StrategyPart.callback` 공개; 테스트 13개 이름 변경, 한 테스트의 fault seam이 `Account.append`로 | fast 1671 · digest 83/83 · pyright 0 |
| P1 | `232` | Panel = 필드마다 name-major Arrow 배열 하나; `Panel.from_table`, `column()`, `block()`, `validity()`, `PanelWindow.matrix()`; `counts/current/latest` 벡터화; `scan.observation_table` + `_ObservationQuery`; numpy 선언 | build 10.7 → 1.2 ms · counts 3.1 → 0.2 · matrix decide 1.5 ms · digest 83/83 |
| P2 | `233` | sample 전략·scaffold 둘·skill reference가 `matrix()` 위에서 계산; `Decimal`은 `Rebalance` 경계에서만; rows grain flavour는 종목별 Decimal 축약 유지; `_shipped.json` 재기록 | fast 1672 · digest 83/83 · 40줄 한도 |
| V | `234` | `data/validation.py` 한 문(`verify_source` · `require_verified` · `verify_roster`); 등록이 `source_digest`·`execution_prices`를 둠; preflight·run·check는 digest만 대조; `validate_execution_table` + 세 diagnosis 삭제; 같은 선언 재등록이 측정만 갈아 끼움; 경계 테스트 + check 스캔 0 | fast 1685 · digest 83/83 · pyright 0 |

닫힌 이슈: `095`, `096`, `097` (모두 `docs/issues/archive/`).

## 2. 결정 로그

- `Panel`은 숫자 아닌 필드를 Arrow로 둔다: 문자열·날짜에는 NaN이 없고, 그런 필드의 모델 API는
  `values`/`series`로 남는다; `matrix()`는 숫자 아닌 필드를 이름으로 거절한다.
- `StrategyEventLoop`/`DataModelEventLoop`는 얇은 서브클래스로 남기지 않고 함수가 된다: `__init__`만
  있는 클래스는 타입으로 철자된 factory다.
- V: 파일이 바뀐 뒤 **같은 선언으로 다시 등록하면 측정된 반쪽**(span · aggregated · digest · 가격 사실)만
  갈린다. 대안(`rm dataset` 뒤 등록)은 거절문이 말하는 fix를 두 단계로 만든다; run의 record는 자기가
  읽은 digest를 갖고 있어 출처는 잃지 않는다.
- V: `extension/conformance.py`는 문 밖이다 — 코드를 로드하지 데이터를 읽지 않는다.
- 옛 문서의 자동 마이그레이션은 없다: `grain`·`field_types` 때처럼 읽는 쪽이 이름으로 거절하고
  (`dataset.unverified`) `register`가 고친다.

## 3. 발견

- `observation_rows`는 이미 duckdb에서 컬럼을 받아 dict 행을 스스로 만들고 있었다: P의 columnar 경로는
  일을 더하는 게 아니라 뺀다.
- preflight의 집행표 key 스캔은 등록이 증명한 축을 다시 증명한다(`(available_at, instrument)`가 그 표의
  `trade_at, instrument`다): V는 사실을 잃지 않고 그것을 지운다. 가격 스캔은 run이 고른 가격에 달려
  있으므로 등록이 모든 후보 가격을 한 번에 재고 preflight는 답을 읽는다.
- `_source_digests`(run)와 `physical_digest`는 이미 있었다: V는 digest를 등록 시점으로 옮기고 나중에
  대조한다.
- 옛 merge 규칙은 측정된 span이 다르면 `dataset.registered`로 거절했다 — `dataset.source_changed`의
  fix("register again")는 되지 않는 명령이었다.

## 4. 남긴 것

- showcase 전략들(`show_002`·`003`·`004`)은 `window.values[name]`으로 읽는다 — 사용자 코드의 자리이고
  digest 기준선이 그 출력을 고정한다.
- 시나리오 stepper(오너의 여섯 시나리오, 10종목, 실제 트레이스)는 이 캠페인 뒤에 쓴다.
