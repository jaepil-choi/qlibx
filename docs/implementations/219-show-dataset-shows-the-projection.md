# 219 — `show dataset` shows the projection

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/093` — `show dataset`이 선언한 projection이 아니라 원천 파일의 행을 돌려준다 |
| **브랜치** | `develop` |
| **앞선 기록** | `218` · `049` (grouped projection) · `173` (`field_types`는 projection의 성질) |

---

## 왜 이 변경이 있는가

`show dataset`은 `register-dataset` skill이 등록의 **확인** 단계로 지목한 명령이다. 그런데 `items`는
`scan.head(source)` — 원천 파일의 `SELECT *`였다. 필드가 컬럼 이름인 등록 20개에서는 둘이 우연히
같았고, 필드가 집계 표현식인 하나 — 전체 축약 규칙을 실은 바로 그 등록 — 에서 선언한 10개 필드 중
9개가 없고 선언하지 않은 9개 컬럼이 있었으며, 반환된 행은 projection이 `settlement_type = 'D'`로
걸러내는 `'A'` 행이었다. 같은 응답의 `fields`·`field_types`·`aggregated`는 projection을 설명했다.
응답이 자기모순이었고, 확인이 확인하지 않았다.

`scan.projection_relation`의 docstring이 이미 규칙을 말한다: *"Anything that must look at what a
model will receive reads this, not the source."* `head`의 반대 논거("what is in this file"과 "what a
model would have seen"을 섞지 말라)는 cutoff와 lookback에 대한 것이고, projection에는 둘 다 없다.

## 무엇이 어떻게 바뀌었는가

- `data/scan.py` — `head(spec, limit, relation=None)`·`row_count(spec, relation=None)`. `relation`은
  `projection_relation`이 만든 서브쿼리.
- `cli/show.py` — `_dataset`이 기본으로 projection relation을 읽는다(read path와 같은 함수, 같은
  `aggregated` 판정). 응답에 **`items_are: "projection" | "source"`**, `rows_total`은 `items`가
  넘기는 것의 수, **`source_rows_total`**은 항상 파일의 수. `--source` 플래그가 파일 행을 요구한다.
  측정된 적 없는 등록(`aggregated`가 `None`)은 projection 모양이 없어 source 행을 돌려주고 그렇게
  말한다.
- `--help`와 `inspect-workspace`·`register-dataset` skill이 비용을 적는다: 집계 등록은 `LIMIT 2`라도
  grouping 전체를 한 번 평가한다.

## 대안과 트레이드오프

- **source head 유지 + `items_are: "source_rows"` 표시만** (보고자의 2안). 기각: 확인 단계가
  확인하지 않는다는 사실을 알리는 것과 확인하게 만드는 것 중 후자가 verb의 목적이다. 비용은 `--help`에
  적고 `--source`를 남겼다.
- **`rows_total`의 뜻 유지(파일 수).** 기각: `rows_total`이 39,307,271인데 `items`는 (instant, instrument)
  당 한 행이면 그것이 보고의 두 번째 모순이다. 이름을 둘로 나눴다. identity projection에서는 두 수가
  같으므로 기존 caller가 보는 값은 변하지 않는다.

## 검증

```
.venv/Scripts/python.exe -m pytest tests/cli/test_commands.py tests/data/test_scan.py -q
  통과 (새: max(close) 집계 등록 → items 키가 {available_at, instrument, high}, items_are
        projection, rows_total == source_rows_total == 3; --source → 파일 컬럼, items_are source;
        identity 등록은 전과 같은 키)
.venv/Scripts/ruff.exe check src/   All checks passed
```

## 남은 것

큰 파일의 집계 등록에서 `show dataset`은 두 번 전체를 훑는다(count 한 번, head 한 번). 한 쿼리로
합치는 것은 가능하지만 `head`와 `row_count`를 하나로 묶는 API 변경이라 미뤘다. `035`(유일한 accessor가
파일보다 90배 느리다)와 같은 결의 문제이고, 그 이슈가 열려 있는 채로 여기 덧붙일 일은 아니다.
