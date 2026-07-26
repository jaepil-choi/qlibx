# Alpha configuration contract

Alpha YAML이 hypothesis와 executable definition의 source of truth다. Alpha pool DB에는
definition을 복제하지 않고 resolved config hash만 저장한다.

필수 top-level key:

- `schema_version`
- `key`: stable logical alpha key
- `family`: `market`, `consensus`, `financial`
- `track`: `trusted`, `financial_shadow`, `legacy`
- `hypothesis`
- `inputs`: logical dataset key mapping
- `signal`: implementation key와 parameter
- `execution.order_calendar_key`
- `execution.lag_days`
- `execution.max_holding_days`
- `neutralization`
- `search`: 실행 전에 고정한 bounded parameter grid

규칙:

- `trusted` alpha의 fixed rebalance/holding interval은 63거래일을 넘을 수 없다.
- Financial alpha는 exact PIT source가 생기기 전까지 `financial_shadow`만 허용한다.
- Consensus와 market을 함께 쓰는 hybrid는 event clock을 소유한 `consensus` family에 둔다.
- 같은 `order_calendar_key` member만 calendar cohort로 crossing한다.
- Resolved config와 input fingerprint가 같으면 같은 deterministic run identity를 사용한다.
