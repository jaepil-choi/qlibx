# 245 — `--limit 0`은 행 0개를 돌려준다: count는 count다

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 하나를 닫는 bounded fix (0.14.2 hotfix) |
| **이슈** | `docs/issues/report-2026-09-10-show-dataset-limit-zero-does-not-return-on-a-large-source` — 닫는다 |
| **설계 근거** | 기록 `077`(run이 쓴 행을 읽는 `--table`, `--limit 0`이 "전부"였던 자리), `093`(`show dataset`이 projection을 읽는다) |
| **브랜치** | `develop` (0.14.1 stamped 뒤) |
| **앞선 기록** | `077`, `093` |

---

## 왜 이 변경이 있는가

enhanced-index testbed(0.11.0 wheel)의 보고. 430 MB · 8,676,023행의 plain `instrument_instant` dataset에
`show dataset equity-daily --limit 0`을 — span과 행 수만 원해서, 행은 0개를 청하는 뜻으로 — 실행했더니 5분
timeout까지 돌아오지 않았고, 한 번은 machine의 free memory를 소진해 옆에서 돌던 671-run 빌드를 죽였다.

원인은 하나다. `--limit 0`은 기록 `077`부터 "**모든** 행"을 뜻했고(`scan.head`: limit이 있을 때만 `LIMIT`;
`_rows`: `limit == 0 or len(rows) < limit`), `show dataset`은 그 모든 행을 `fetchall()`로 Python dict에
올린 뒤 JSON 봉투 하나로 내보낸다. 4.2M행 합성 parquet(44 MB)에서 그 경로는 **100.5 s, Python heap +1.78 GB**
— 8.7M행이면 그 두 배다. 돌아왔더라도 8.7M행 JSON은 stdout으로 읽을 것이 아니다.

## 무엇이 어떻게 바뀌었는가

**`--limit N`은 최대 N행이고 `0`은 0행이다 — `show dataset`과 `--table` 둘 다.** 0이 무한을 뜻하는 특수값은
count라는 플래그의 뜻과 어긋나고, 보고자(이 패키지의 사용자인 agent)가 그것을 0으로 읽은 것이 그 증거다.

- `data/scan.py::head`: `limit <= 0`이면 query 없이 `[]`. `LIMIT` 절은 항상 붙는다.
- `cli/show.py::_rows`: `len(rows) < limit`만. `--limit`의 help가 새 뜻과, 전부를 원하면 봉투의 `rows_total`만큼
  청하라는 것을 말한다.
- skill 문서 셋이 "`--limit 0` returns everything"을 가르쳤다: `analyze-result/references/reading-a-record.md`,
  `inspect-workspace/SKILL.md`, `introduce-vqapr/references/sample-journey.md`. 예시는 `--limit 1000`으로, 문장은
  "at most N rows; 0 returns none; a whole table is `--limit <rows_total>`"로.

**깨지는 변화.** `--limit 0`으로 표 전체를 읽던 호출자는 `rows_total`만큼(첫 호출이 알려준다) 청해야 한다.
0.14.2 릴리스 노트의 마이그레이션 절에 적었다. 기록 `077`의 결정을 뒤집는 것이며, 이유는 위 한 문단이다.

**바꾸지 않은 것.** `rows_total`은 여전히 projection relation 위의 `count(*)`다 — plain 등록에서는 duckdb가
parquet footer로 답하므로(아래 0.86 s에 포함) 보고자가 의심한 "aggregated가 아닌데 full pass"는 없었다.
aggregated 등록의 `count(*)`는 기록 `093`이 말한 대로 grouping 한 번이다.

## 검증

| 검사 | 결과 |
|---|---|
| 합성 parquet 4,200,000행(3,000 종목 × 1,400일, 44 MB), `vqapr register` 1.7 s 뒤 `show dataset equity-daily --limit 0` | **0.86 s**, `returned: 0`, `rows_total: 4200000`, span 있음, stdout 731 bytes. `--limit 5`: 0.82 s |
| 같은 parquet, 0.14.1의 `head(limit=0)` 경로(모든 행을 dict로) | 100.5 s, Python heap peak +1.78 GB |
| `tests/cli/test_commands.py::test_show_dataset_reads_back_what_a_dataset_holds` (`--limit 0` 단언을 새 뜻으로) · `tests/cli/test_show.py`(`limit=0` → `100`) | 통과 |
| `tests/cli` · `tests/characterization` | 통과 (0.14.2 노트의 `test_all`에 포함) |
| `ruff check src/` · `pyright` | clean · 0 errors |
