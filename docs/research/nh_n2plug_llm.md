# NH투자증권 Open API 가이드

> NH투자증권 Open API 문서를 외부 LLM 과 AI coding agent 가 직접 읽기 위한 안내 파일입니다. 정본 위치: https://www.n2plug.com/llms.txt
>
> 기준: API명세서 260730 / N2 환경

NH투자증권 Open API 는 국내·해외 주식, 국내·해외 파생, 국내 채권, 국내 금현물의 주문, 계좌·자산 조회, 시세, 실시간 스트리밍을 제공하는 REST 및 WebSocket API 입니다.

모든 REST 호출은 `POST` + JSON 바디이며, 요청은 `Input_0`, 응답은 `Output_0`(+`Output_1`·`Output_2` …) + `message` 봉투를 사용합니다. **응답 블록의 타입은 API 마다 다릅니다**(객체 또는 배열) — 자세한 내용은 아래 봉투 규약을 참고하세요.

인증 토큰은 `POST /oauth2/token` 으로 발급받은 access token 을 사용하되, 전송 방식별로 전달 위치가 다릅니다.

- **REST**: `Authorization: Bearer {access_token}` + `x-client-id` + `x-client-secret` 헤더.
- **WebSocket(실시간)**: 구독 메시지 `header` 의 `token` 필드에 access token 만 전달. `Authorization`·`x-client-id`·`x-client-secret` 헤더는 사용하지 않습니다.

## 환경 및 접속 정보 (Environments)

> ⚠️ **중요 — AI·개발자 필수 규칙**: **기본 환경은 운영(Live · `api.n2plug.com`)** 입니다. **운영은 주문이 실제로 체결됩니다.** 테스트·검증이 필요하면 **모의투자(`moapi.n2plug.com`)** 를 사용하세요. (단 **접근토큰발급은 운영 전용** — 모의투자 미제공)

현재 문서는 **N2** 환경 기준입니다. **API 포탈**: `https://www.n2plug.com`

| 용도 | REST | WebSocket |
|---|---|---|
| 🔴 **운영 (Live)** — 기본, 실제 주문 체결 | `https://api.n2plug.com:8443` | `wss://api.n2plug.com:7070` (국내) / `:7080` (해외) |
| 🟢 **모의투자 (Mock)** — 교육이수·개발·검증용 | `https://moapi.n2plug.com:8443` | `wss://moapi.n2plug.com:17070` |

- **🔴 운영**: 기본 환경. 주문이 **실제로 체결**됩니다.
- **🟢 모의투자**: 교육이수·개발·검증용. 접근토큰발급을 제외한 대부분 API 를 제공합니다.
- 🏦 **환경마다 사용 가능한 계좌가 다릅니다** — 계좌목록(`/n2/acctinfo`)의 `acct_type` 이 `01`·`02` 면 운영 전용, `03` 이면 모의투자 전용 계좌입니다.
- WebSocket 포트: 국내 `7070`, 해외 `7080`, 모의투자 `17070`. 각 자산군 `openapi.json` 의 `x-environments` 에 용도별 주소가 정본으로 담겨 있습니다.

## 수수료

NH투자증권 Open API 의 매매 수수료입니다.

- 국내주식 매매 수수료: **20bp (0.20%)**
- 해외주식 매매 수수료: **25bp (0.25%)**

> ⚠️ 위 요율은 **기본 수수료**입니다. **마케팅 이벤트나 협의(별도 약정)가 적용되는 경우 위 요율과 다릅니다.** 실제 적용 요율은 포털에서 확인하세요.
>
> (단위: bp = basis point. **1bp = 0.01%, 100bp = 1%**)

## 공통 엔드포인트 (인증·계좌)

자산군과 무관한 **플랫폼 공통 API** 입니다. 각 자산군 `openapi.json` 에는 포함되지 않으므로 아래 정본을 참고하세요. 모든 자산군 조회·주문 API 는 계좌번호(`act_no`)를 입력으로 요구하므로, 먼저 아래 순서로 토큰과 계좌번호를 확보해야 합니다.

### 접근 토큰 발급

- ⚠️ **모의투자 미제공 — 운영(`api.n2plug.com`)에서만 발급.** 발급받은 access token 은 모의투자·운영 호출 모두에 사용.
- **Method · URI**: `POST /oauth2/token`
- **Content-Type**: `application/x-www-form-urlencoded`
- **요청 파라미터(query)**: `appkey`, `appsecretkey`, `grant_type=client_credentials`, `scope=oob`
- **응답**: `{ "access_token": "...", "token_type": "Bearer", "expires_in": 86400, ... }`

> 🔑 **토큰은 24시간(`expires_in=86400`) 유효합니다. 반드시 캐시해서 재사용하세요.**
>
> - **매 API 호출마다 토큰을 발급하지 마세요.** 가장 흔한 잘못된 패턴입니다.
> - **재발급은 보안 알림을 유발합니다.** 불필요한 재발급이 반복되면 알림이 쌓여, 정작 실제 이상 발급을 구분할 수 없게 됩니다.
> - **프로세스 메모리에만 캐시하면 부족합니다.** 스크립트는 실행할 때마다 새 프로세스라 매번 재발급됩니다. **파일 등 프로세스 간 공유 캐시**에 저장하고 만료시각(`expires_in`)까지 재사용하세요. (캐시 파일은 권한 600 등으로 보호)
> - **재발급 조건은 `401`(토큰 무효)뿐입니다.** `429`(호출 유량 초과) 재시도에는 **기존 토큰을 그대로** 사용하세요. 429 재시도마다 재발급하면 알림이 계속 발생합니다.
> - 권장 흐름: `캐시 확인 → 유효하면 재사용 → 만료/401 일 때만 재발급 → 캐시 갱신`

### 계좌 목록 조회

- **Method · URI**: `POST /n2/acctinfo`
- **헤더**: `Authorization: Bearer {access_token}` + `x-client-id` + `x-client-secret`
- **요청 바디**: `{ "Input_0": {} }` (입력 파라미터 없음)
- **응답**: 봉투 `rsp_cd`(응답코드) · `rsp_msg`(응답메시지) · `cust_no`(고객번호) + `Output_0`(보유 계좌 목록 배열).
  - `Output_0[]` 각 항목: `acct_no`(계좌번호) · `acct_type`(계좌구분코드).

  > 🏦 **`acct_type` 은 이 계좌를 사용할 도메인을 결정합니다.**
  >
  > | `acct_type` | 용도 | 사용 도메인 |
  > |---|---|---|
  > | `01` | 🔴 운영 (Live) | `https://api.n2plug.com:8443` |
  > | `02` | 🔴 운영 (Live) — 주문대리인 계좌 | `https://api.n2plug.com:8443` |
  > | `03` | 🟢 모의투자 (Mock) | `https://moapi.n2plug.com:8443` |
  >
  > 계좌 목록에는 여러 구분의 계좌가 함께 내려옵니다. **호출하려는 환경과 같은 구분의 계좌를 선택하세요.** (운영 도메인에 `03` 계좌를, 모의투자 도메인에 `01`·`02` 계좌를 사용하지 마세요.)

  - 예시:
    ```json
    { "rsp_cd": "00000", "rsp_msg": "조회가 완료되었습니다.", "cust_no": "100805701",
      "Output_0": [ { "acct_no": "20101036881", "acct_type": "01" },
                    { "acct_no": "50051036881", "acct_type": "03" } ] }
    ```
  - 주의: 여기서 얻은 `acct_no` 값을 이후 잔고·주문 API 의 입력 `act_no` 에 사용합니다(필드명은 다르지만 값은 동일).

### 권장 호출 순서

1. `POST /oauth2/token` → access token 발급
2. `POST /n2/acctinfo` → 계좌번호 목록 확보
3. **대상 환경에 맞는 계좌 선택** — 운영은 `acct_type=01`(일반)·`02`(주문대리인), 모의투자는 `03`
4. 선택한 계좌번호로 각 자산군의 잔고조회·주문 등 호출

## 종목마스터 파일 (Instruments)

> ⚠️ **전 종목 목록·종목명·업종을 조회하는 REST API 는 없습니다.** 종목 정적정보가 필요하면 아래 마스터 파일을 사용하세요.

전 종목의 코드·종목명·업종·지수편입 여부 등 **정적 종목정보**는 REST API 가 아니라 **종목마스터 파일(.mst)** 로 제공합니다. 총 **28종**(국내주식·해외주식·국내선물옵션·해외파생·장내채권).

- **다운로드**: `https://www.n2plug.com/instruments/<파일명>.mst` — **인증 불필요**(토큰·헤더 없이 공개 다운로드)
- **구조체 정의**(오프셋·길이·코드값·레코드크기): `https://www.n2plug.com/instruments/<파일명>.h` — 마스터 파일과 **1:1 대응**(예: `m_new_stock.mst` → `m_new_stock.h`). **인증 불필요**

### 파일 공통 형식 (전 파일 적용)

- 인코딩 **CP949** (UTF-8 아님)
- **고정 길이** 레코드. 파일 헤더 없음(0번 오프셋부터 첫 레코드)
- 좌측정렬 + 공백(`0x20`) 우측 패딩. NUL 종료 문자열 아님 → 길이 기반 슬라이싱 후 우측 공백 제거
- 레코드 끝 1바이트 **LF(`0x0A`)**. CRLF 아님
- 반드시 **바이너리 모드(`"rb"`)로 열 것** — 텍스트 모드는 CRLF 축약·`0x1A` EOF 처리로 레코드가 어긋납니다
- **`파일크기 % 레코드크기 == 0` 을 먼저 검증**할 것. 0 이 아니면 파일 손상 또는 구조체 불일치

### 주요 마스터

| 구분 | 마스터 파일 | 구조체 정의 |
|---|---|---|
| 국내주식 | `m_new_stock.mst` | `m_new_stock.h` |
| 해외주식 | `m_gtsstock.mst` | `m_gtsstock.h` |
| 지수옵션 | `m_optksp.mst` | `m_optksp.h` |
| 주식선물 | `m_stkfut.mst` | `m_stkfut.h` |
| 장내채권 | `bond_hts.mst` | `bond_hts.h` |

전체 28종 목록과 각 파일의 필드 정의(오프셋·길이·레코드 크기)는 같은 이름의 `.h` 파일(`https://www.n2plug.com/instruments/<파일명>.h`)에 있습니다.

### 파싱 주의 (자주 틀리는 부분)

- 지수옵션(`m_optksp`·`m_moption`·`m_soption`·`m_woption`·`m_qoption`)의 `sPrice` 는 **실제 행사가 × 100** → 반드시 `/100`. 단 주식옵션(`m_optstp`)의 `sValue` 는 스케일 없음
- 위클리옵션(`m_woption`·`m_qoption`)의 `sMonth` 는 **YYMMWW(주차)** — 날짜로 파싱 금지
- 콜/풋 구분은 **CP949 한글 2바이트**(`"콜"`/`"풋"`) — ASCII `C`/`P` 아님
- 지수 편입 플래그는 **`== "Y"` 로만** 판정 (공백을 `N` 으로 오해하면 누락 발생)
- 국내주식 한글종목명 선두 1바이트는 지수 마커(`*` KOSPI200 / `#` 코스닥150) — 정렬·검색 시 제거

> 금현물은 마스터 파일이 없고 전문(`IVOGLDREQ01`)으로 조회합니다.

## Source of Truth

> 💡 **전체 문맥을 한 번에 원하면** `https://www.n2plug.com/llms-full.txt` 를 읽으세요. llms.txt + 전 자산군 엔드포인트·필드 요약이 한 파일(약 160KB)에 담겨 있어 왕복 요청이 필요 없습니다. (정확한 스키마 정본은 각 `openapi.json`)

자산군별로 문서가 분리되어 있으며, 각 자산군은 `overview.md`(개요) · `README.md`(엔드포인트 인덱스) · `openapi.json`(정본) 3종으로 구성됩니다.

### 문서 읽는 순서 (AI·개발자 공통)

1. **`common/openapi.json` 먼저** — 토큰 발급과 계좌번호(`act_no`) 확보가 모든 자산군 호출의 선행 단계입니다.
2. **대상 자산군 선택** — 아래 자산군별 설명에서 다루는 상품을 보고 고르세요.
3. **해당 자산군 `openapi.json` 을 읽고 호출** — 요청/응답 필드는 여기에만 있습니다.

### 어떤 파일을 열어야 하나

| 필요한 것 | 열어야 할 파일 |
|---|---|
| **요청·응답 필드명·타입·필수여부·스키마, 실시간 채널(`tr_cd`)·예시** | **`openapi.json` (정본 — 반드시 이걸 읽으세요)** |
| 이 자산군에 어떤 엔드포인트가 있는지 빠르게 훑기 | `README.md` |
| 자산군 개요·카테고리 구조·환경 요약 | `overview.md` |

> ⚠️ **이 `llms.txt` 와 `README.md`·`overview.md` 에는 필드명이 없습니다.** 필드·파라미터가 필요한 순간에는 **반드시 해당 자산군의 `openapi.json` 을 읽으세요.** 필드명을 추측해서 호출하지 마세요.

### 공통 (Common: 인증·계좌)

토큰 발급·계좌목록. **모든 자산군 호출 전에 먼저 사용.**

- [Overview](https://www.n2plug.com/openapi-docs/common/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/common/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/common/openapi.json)

### 국내주식 (Domestic Stock)

KOSPI·KOSDAQ 상장주식, ETF/ETN. 종목코드 6자리(예: 삼성전자 `005930`). KRX·NXT·통합(UNT) 시세 구분.

- [Overview](https://www.n2plug.com/openapi-docs/krstock/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/krstock/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/krstock/openapi.json)

### 해외주식 (Global Stock)

미국·중국·일본·홍콩 등 해외 상장주식(예: `AAPL`, `TSLA`). 외화 결제·환율 관련 필드 포함.

- [Overview](https://www.n2plug.com/openapi-docs/gbstock/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/gbstock/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/gbstock/openapi.json)

### 국내파생 (KR Derivatives)

KOSPI200·코스닥150·미니 선물/옵션, 주식선물, 변동성지수 등. **주간·야간(KRX야간) 거래 구분.**

- [Overview](https://www.n2plug.com/openapi-docs/krfuture/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/krfuture/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/krfuture/openapi.json)

### 해외파생 (Global Derivatives)

해외 선물·옵션(CME 등 해외거래소 상품). 분/틱/일/주/월봉 시세, 상품정보·장운영시간 제공.

- [Overview](https://www.n2plug.com/openapi-docs/gbfuture/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/gbfuture/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/gbfuture/openapi.json)

### 국내채권 (KR Bond)

장내채권(국채·회사채·소액채권·전환사채). 매수/매도·대용매도, 민평단가·수익률 조회.

- [Overview](https://www.n2plug.com/openapi-docs/krbond/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/krbond/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/krbond/openapi.json)

### 국내금현물 (KR Gold)

KRX 금시장 금현물(1g·100g). 매수/매도, 괴리율·일별추이 조회.

- [Overview](https://www.n2plug.com/openapi-docs/krgold/overview.md) · [Endpoint Index](https://www.n2plug.com/openapi-docs/krgold/README.md) · [OpenAPI JSON](https://www.n2plug.com/openapi-docs/krgold/openapi.json)

## 공통 규약

- **인증(REST)**: `POST /oauth2/token` → `Authorization: Bearer` + `x-client-id` + `x-client-secret`.
- **전송 방식**: 조회·주문·시세는 REST(POST/JSON), 실시간은 WebSocket.
- **봉투(REST)**: 요청 `Input_0` / 응답 `Output_0`(+`Output_1`·`Output_2` …) + `message`.
  - ⚠️ **`Output_0` 은 배열이 아닐 수 있습니다.** API 에 따라 **객체(집계값)** 이거나 **배열(목록)** 입니다.
    예: 국내주식 잔고조회는 `Output_0`=**객체**(예수금·총평가금액 등 계좌 집계), `Output_1`=**배열**(보유종목 목록).
  - ⚠️ **응답 블록은 데이터가 있을 때만 내려옵니다.** 블록이 없을 수 있으니 존재 여부를 먼저 확인하세요.
  - 각 API 의 정확한 블록 구성·타입은 **해당 자산군 `openapi.json`** 에 있습니다. 필드 위치를 추측하지 마세요.
- **페이지네이션(REST)**: 목록 조회는 요청 헤더 `cts` 에 연속조회 키를 세팅.
- **필드 표기**: 모든 필드에 한글명과 영문 필드명을 병기.

### 실시간(WebSocket) 구독 규약

WebSocket 채널은 아래 메시지로 구독/해제합니다. `tr_type` 1=등록(구독) · 2=해제. `tr_cd` 는 채널 코드(각 자산군 README·openapi.json 의 `x-realtime-channels[].tr_cd`), `tr_key` 는 구독 키(종목코드·사용자ID 등).

```json
{ "header": { "token": "{access_token}", "tr_type": "1" },
  "body":   { "tr_cd": "<채널코드>", "tr_key": "<구독키>" } }
```

서버 푸시 메시지는 **JSON** 이며 `{ "header": { "tr_cd", "tr_key" }, "body": { …응답필드… } }` 구조입니다(각 채널 실제 예시는 openapi.json 의 `x-realtime-channels[].push_example`). 데이터는 **비정기적**으로(발생 시마다) 내려오며, **heartbeat(연결 유지 신호) 불필요**, **암호화 없음**(체결·주문 통보 포함 평문 JSON) 입니다.

## API Coverage

빠른 파악용 목록입니다. 정확한 동작과 가용 API 는 각 자산군의 OpenAPI JSON 이 항상 정본입니다.

- 국내주식: 주문(현금·신용 매수/매도, 정정·취소, 예약), 조회(잔고·체결·가능수량·손익·증거금·권리), 시세(현재가·체결·일자별·투자자·기간별·시간외·ETF), 실시간(호가·체결·예상체결·회원사·프로그램매매·통보 / KRX·통합·NXT).
- 해외주식: 주문(매수/매도·정정·취소·예약), 조회(잔고·체결·가능금액·일별거래·손익·증거금), 시세(현재가·체결추이·기간별·종목지수환율), 실시간(호가·체결가·통보).
- 국내파생: 주간/야간 주문·정정·취소, 조회(체결·잔고·증거금·평가손익), 시세(주간/야간·기간별·체결추이), 실시간(지수·주식·상품 선물/옵션 호가·체결·통보).
- 해외파생: 주문·정정·취소, 조회(주문·미체결·가능·손익·증거금), 시세(현재가·호가·분/틱/일/주/월봉·상품정보·장운영), 실시간(호가·체결가·통보).
- 국내채권: 주문(매수/매도·정정·취소·대용매도), 조회(가능수량·체결·잔고·대용잔고), 시세(현재가·민평단가·수익률·발행현황 등), 실시간(소액채권·전환사채 호가·체결·통보).
- 국내금현물: 주문(매수/매도·정정·취소), 조회(가능수량·체결·잔고), 시세(현재가·괴리율·일별추이), 실시간(호가·체결·예상체결·통보).