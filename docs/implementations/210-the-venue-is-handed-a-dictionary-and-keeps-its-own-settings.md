# 210 — The venue is handed a dictionary and keeps its own settings

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M10 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 3c) — **Stage 3 완료** |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §6.1 (계약은 좁다 · 설정은 venue의 것) · §6.4 (사전은 창고가 아니다) · §4 배선표 (Exchange = 주문 + 시장상태 + 계좌 + 종목사전) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `209` (Compliance watches on the market clock) |

---

## 왜 이 변경이 있는가

설계 §6.1의 계약은 넷을 받는다 — 주문 배치, 그 시각의 시장 상태, 계좌 스냅샷, **주문에 등장하는
종목의 정체**. M3가 그 넷째를 만들었지만 `rules.with_registry(registry)`로 view 안에 실어 보냈다:
사전이 `ExecutionCall`의 필드가 아니라 rules의 속성 하나였다. 계약이 "venue는 사전을 받는다"고 말하지
않았다.

그리고 §6.1의 둘째 문장 — *"규칙 on/off는 venue의 설정이다. 스키마는 venue가 정의하고, 프레임워크는
'venue는 설정을 갖는다'만 안다"* — 는 코드에 없었다. `venues/krx.py`의 docstring이 *구현함 / 구현 안
함*을 산문으로 적고 있었고, 수수료·거래세는 모듈 상수였다. 거래세를 끈 KRX는 파일을 고쳐야 만들 수
있었고, 어느 설정으로 돌았는지는 record가 아니라 `source_digest`의 바이트를 열어야 알 수 있었다 —
scaffold의 주석이 그렇게 말하고 있었다(*"It is not a field in the record"*).

---

## 무엇이 어떻게 바뀌었는가

### `ExecutionCall.instruments`

```python
ExecutionCall(at, orders, account, snapshot, instruments: InstrumentRoster, rules)
```

사전이 필드다. `rules`는 venue 자신의(바인딩 안 된) view로 들어와도 되고, `__post_init__`이 사전에
묶는다. **다른 사전에 묶인 view는 거절한다** — 조용히 다시 묶지 않는다. 사전은 통째로 온다(§6.4:
시간축이 없으므로 창으로 읽지 않는다). handler는 `registry`를 그대로 넘기고, roster가 없는 조립(테스트)
은 빈 사전을 넘긴다 — 빈 사전은 "선언 없음"이고, 선언 없는 종목의 charge는 거절된다. M3의 runtime
게이트가 그 앞에서 이미 거절하므로 production 경로에서는 닿지 않는 방어선이다.

### `Exchange.settings`

```python
class Exchange(Component):
    @property
    def settings(self) -> Mapping[str, ModelMemory]: return {}
```

venue가 무엇을 모델링하는지를 **데이터로** 선언한다. 스키마는 venue의 것. `load_exchange`가
strict-JSON임을 검사한다(`component.execution_profile_invalid` — "settings must be a portable
mapping"). record의 `strategy.json`에 `exchange: {component_id, fingerprint, settings}` 블록이 생겼다
— `vqapr show strategy`가 보여준다.

KRX:

```python
KrxExchange(listings | ids, exchange_id="krx", *, commission_rate, sale_tax_rate, price_limits=None)
KrxSettings(commission_rate, sale_tax_rate)  # .of(str|Decimal) — config는 문자열, 코드는 Decimal
settings == {profile, quantity_unit, commission_rate, sale_tax_rate, price_limits, short_sales,
             partial_fills, not_modelled: [...]}
```

docstring의 *Implemented / Not implemented* 목록이 `KRX_NOT_MODELLED` 튜플과 `settings`의 키가 됐다.
수수료·거래세가 생성자 인자라 **같은 파일을 config만 다르게 두 번 등록하면 두 venue**다 — fingerprint가
config를 접으므로 두 run identity가 갈리고 창고에 따로 들어간다(AC-11). `price_limits`는 listing의
사실(`KrxTradeRule.price_limit_rate`)이라 설정으로 두 번 말하지 않는다: id로 받을 땐 스위치, 명시적
rule로 받을 땐 rule이 말하고 스위치는 비워야 한다. `settings["price_limits"]`는 rule에서 읽는다.

Academic: `{"profile": "academic", "costs": "none", "partial_fills": "never"}`.

### AC-11 — `tests/acceptance/test_a_venue_setting_is_a_different_run.py`

한 venue 파일, 두 등록(`krx-taxed`, `krx-untaxed: {config: {sale_tax_rate: "0"}}`), 같은 회전 전략,
같은 가격. 과세 run의 주식 매도는 세금이 붙고 비과세 run은 0; `strategy.json`의
`exchange.settings.sale_tax_rate`가 `"0.002"`/`"0"`; fingerprint가 다르고; fill 테이블의 `run_id`가
서로소; `taxed-weights`·`untaxed-weights`가 둘 다 `list datasets`에 있다.

### 발견해 고친 것 — 저장된 run은 `writes`를 공개하지 않고 있었다

AC-11의 마지막 단언이 처음에 실패했다. `_publish_allocation`이 `result.final_state.recorder_rows`에서
weight 행을 읽는데, **store가 있는 run은 행을 record로 흘려보내고 root에 남기지 않는다.** 그래서
`vqapr run`(항상 store)은 M2 이후 한 번도 allocation을 창고에 넣은 적이 없고, in-process `run()`만
넣고 있었다. showcase들은 record에서 손으로 등록해 왔기 때문에 아무것도 알아채지 못했다. 이제 store가
있으면 record의 `vqapr.weight`를 `read_table`로 읽어 공개하고, 등록은 명령이 연 workspace를 통해 한다
(두 번째 open은 `test_one_run_command_opens_the_workspace_document_once`가 잡았다).

### 잃은 것

- `KrxExchange`의 bare-id 형태가 `krx_listing`(plain `TradeRule`) 대신 `krx_listings`(`KrxTradeRule`,
  rate None)를 쓴다. 동작은 같고 타입만 KRX의 것이다.
- `tests/exchange/test_a_rosterless_run_is_refused_by_a_categorised_venue_and_served_by_a_flat_one`의
  KRX 절반이 `ValueError("no instrument roster reached")`에서 `KeyError("no registered instrument
  describes")`로 — call이 항상 사전을 나르므로 "roster가 안 왔다"는 상태가 없어졌다. flat venue 절반은
  view 수준 주장이라 그대로다.
- academic 테스트 더블은 이제 사전을 묶는다(`tests/exchange/support.py::bound`) — 셋을 factor로 선언.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1652 passed (209s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      14/83 이동 → 재기록 → 83/83
```

원인표: `strategy.json`에 `exchange` 블록이 생겼다 — 전략 record 전부. 테이블은 안 움직였다.

| 무엇 | 몇 개 | 왜 |
|---|---|---|
| `strategy.json` (전략 record 전부: 005 alpha, 006 reversal·momentum, 007, 008 세 멤버 × replicate 둘) | 14 | `exchange: {component_id, fingerprint, settings}` 블록이 새로 생겼다 |
| `run.json` · datamodel record · 테이블 | 0 | `ExecutionCall`의 모양은 record에 안 접히고, venue의 동작은 그대로다 |

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **빈 사전 ≠ 사전 없음.** `ExchangeRulesView.notional`의 fallback(registry None → base sizing)은
  registry가 빈 roster면 타지 않는다. call이 항상 사전을 나르므로 venue 테스트는 사전을 묶어야 한다.
- **`Decimal`은 record에 못 들어간다.** `settings`는 문자열로 적는다(`str(rate)`); `load_exchange`가
  `normalize_memory`로 잡는다.
- **테스트가 `krx_listings`라는 글자를 scaffold에서 찾고 있었다.** scaffold 본문을 바꾸면 그런 단언을
  찾는다(`test_krx_cost_journey`).
- **`vqapr run`이 창고에 아무것도 안 넣고 있었다.** "showcase가 통과한다"는 in-process 경로의 증거지
  CLI 경로의 증거가 아니다. 두 경로가 갈리는 곳(store 유무)은 둘 다 테스트해야 한다.

---

## 다음 기록이 이어받을 것

- **Stage 3이 끝났다.** 확장점은 DataModel · StrategyModel · Exchange · Compliance, 자리 하나(Accrual).
- **Stage 4 (M11–M12).** `LedgerEntry` + `Account` = append 권한(§5), `Prepared*` 통합 + `freeze` 축소.
  둘째 척추 변경 — M0 기준선과 회귀 비교.
