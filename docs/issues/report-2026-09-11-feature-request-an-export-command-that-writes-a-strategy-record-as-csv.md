# Feature request: an export command that writes a strategy record's daily NAV and tables as CSV with numeric columns

**Kind: feature request.**

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.4` wheel for the runs; the CLI and skills were re-checked on develop `173f8c7e` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, runs `B-1` (opus 5), `B-2` (sonnet 5), `B-3` (haiku 4.5) |

## The problem it solves

Every vqapr agent had to hand the result over as plain files: a daily NAV and a log of entries and
exits, which is what a user or a comparison script reads. Each wrote its own exporter, and each hit
at least one error in it:

| run | exporter | lines | errors on the way |
|---|---|---|---|
| B-1 | `work/export_enhanced.py` | 87 | `TypeError`: tuple keys in `json.dumps` |
| B-2 | `project/build_enhanced_outputs.py` | 136 | `TypeError`: `Decimal += str`. Two `RunRecordMissing`: a wrong run path, then two strategy records in one run |
| B-3 | `process_results.py`, `finalize_results.py` | 118 + 176 | `TypeError`: `'<' not supported between str and int` |

The same logic was rewritten three times. It takes the `_ACCOUNT` rows of `vqapr.account`, keeps the
last valuation row per session, and turns the text-valued numbers of `vqapr.fill` and
`vqapr.weight` into numbers. It then joins the strategy's own table with fill prices.

## What exists today

- **`vqapr show strategy <run>/<id> --table <t> --limit N` returns JSON.** Numbers arrive as
  strings, for example `"cash": "1461509043.15829227"`, and the rows come in record order. There
  is no daily NAV view and no file output.
- **`read_strategy_table` and `strategy_report` are library calls.** The `analyze-result` skill
  says "There is no reporting CLI". Its `panels-from-tables.md` documents that some numbers come
  back as text and must be converted with `.astype(float)`. All three agents still tripped on the
  conversion.

## Proposal

A command such as:

```text
vqapr export <run-id>/<strategy-id> --out <dir> [--tables all|nav,weights,fills,holdings,<custom>] [--format csv|parquet]
```

It would write:

| file | columns |
|---|---|
| `nav.csv` | `date, nav, cash`, one row per session: the last valuation of the session |
| `weights.csv` | `date, instrument, weight`, the intended weights per decision |
| `holdings.csv` | `date, instrument, quantity, price, value`, per session |
| `fills.csv` | `date, instrument, requested_quantity, dealt_quantity, price, commission, tax, reason` |
| `<table>.csv` | each table the strategy formed with `TableSpec`, as recorded |
| `report.json` | `strategy_report(...).as_record()` |

Numeric columns would be numeric, written from `Decimal` without a float round trip. Dates would
be in the run's timezone. The command would print the files it wrote, and on a run with several
records it would refuse and name them, as the readers already do.

## How the rerun will measure it

In the testbed rerun, the B agents should produce `outputs/enhanced_nav.csv` from one command, with
no exporter script and no type errors. The evaluator reads the exported NAV directly.
