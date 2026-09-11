# 한 읽기 캠페인 — record를 숫자로 읽고, 한 주소로 부르고, 한 명령으로 넘기고, scaffold 하나가 부품을 보인다

**2026-09-11 · branch `redesign/one-reading` · records `264`–`267` · 완료.**

## 왜

incremental testbed(`kwam-enhanced-index/vqapr-incr-testbed`, vqapr 0.14.4)에서 기존 workspace에 전략 하나를 더하는
비용이 pandas의 1.8배(opus) · 3.8배(sonnet)였다. 세 B 에이전트의 대화 기록을 따라가 보면 비용이 두 곳에서 났다.

1. **authoring API를 손으로 읽었다** — B-1 pydoc 84 KB, B-2 `help()` 41 KB. 둘 다 `vqapr new strategy`를 돌리고
   파일을 버렸다: scaffold가 읽기 하나와 `Rebalance`만 보이고 자기 표·`self.memory`·두 번째 읽기는 주석 두 줄로만
   가리켰다.
2. **결과를 파일로 넘기는 exporter를 셋 다 새로 짰고 셋 다 넘어졌다** — `Decimal += str`, `str < int`, NaN NAV,
   CLI 형식의 주소를 Python에 넘겨 `RunRecordMissing`, `str` store로 `TypeError`.

두 번째의 절반은 문서가 아니라 결함이었다: fill·weight writer가 숫자를 `str(...)`로 기록해서 어느 reader도 숫자로
되돌릴 수 없었고, skill이 "어떤 숫자는 텍스트로 온다"고 그 결함을 설명하고 있었다.

## 오너 판정 (2026-09-11)

- testbed가 요청한 `vqapr new strategy --recipe`는 만들지 않는다 — 같은 필요에 문이 둘이 되고, 레시피 절반은 전략
  코드가 아니다. `new`가 내는 template 하나에 자세한 이름표를 붙인다.
- 숫자는 쓰는 곳에서 고치고, 옛 record도 열 이름으로 되돌린다.
- export는 만들되 좁게: 조인과 parquet 형식은 없다.

## 한 것

| record | 한 문장 | 비유 |
|---|---|---|
| `264` | fill·weight 표가 숫자를 숫자로 기록하고, 옛 record의 텍스트 열은 reader가 이름으로 되돌린다 | 라벨이 틀린 병을 설명서로 경고하는 대신 라벨을 고친다 |
| `265` | `record_address` 하나: reader와 report가 `str` store와 CLI의 `<run>/<ref>`를 받는다 | 같은 집에 주소 표기가 둘이면 우편물이 돌아온다 |
| `266` | `vqapr export`: report가 재는 grid를 `nav.csv`로, 표를 기록된 대로, report를 `report.json`으로 | 손님마다 변환기를 짜게 하지 말고 접시에 담아 낸다 |
| `267` | strategy scaffold가 자기 표(`self.recorder`)·`self.memory`·두 번째 읽기·체결 사실의 자리를 보이고, `call.recorder`는 `self.recorder`를 말한다 | 요리책에 샘플 요리를 더하는 대신 레인지 하나의 손잡이마다 이름표 |

## 하지 않은 것

- 레시피, 전략 표 × 체결가 조인, `--format parquet`.
- ledger `detail`의 텍스트 — 표의 행을 만드는 한 자리에서 숫자로 바꾼다.
- 0 비중(record `260`, 다른 세션), run 선언의 시계(record `259`).

## 다른 세션과 나눈 것

같은 날 main checkout의 다른 세션이 records `259`–`263`을 develop에 넣었다. 이 캠페인은 worktree에서 돌고, develop에
rebase하며 `261`의 `sized_quantity` 열도 숫자로 기록하고 `RECORDED_AS_TEXT`에 넣었다. 새 record 번호는 그쪽이 `268`부터.

## 검증

rebase 뒤 `uv run python -m pytest tests/ -q -m ""` — 각 record의 검증 표와 계획
(`.agent/plans/completed/one-reading-campaign.md`, 로컬)에 수치. 재실행(testbed의 같은 여섯 칸)이 두 요청의 측정 — API
조회량, B/A 비용, 정확도 — 으로 이 판정을 다시 잰다.
