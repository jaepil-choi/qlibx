# 018 Opt-in sample journey

## Intent

Provide the optional fresh-user journey required by PRD section 6.1 without silently creating files
or presenting sample logic as built-in alpha. The sample must run from the installed package through
public facade/CLI contracts and preserve user-modified files.

## Implementation

- Bundle a product-owned `basic-real-dw-journey-v1` resource with four bounded real-DW-derived rows,
  explicit registration, local Strategy code, provenance manifest, and public-only runner.
- `QlibxProject.materialize_sample` and `qlibx project sample` preview by default. `--apply` copies to
  `examples/qlibx_owned/basic`; identical files are unchanged and modified files cause a conflict
  without overwrite.
- The runner registers the data, executes a direct Strategy, publishes one portable stored signal,
  reuses it in long-short and long-only Strategy operations, performs optional long-only portfolio
  construction, calculates PIT signal analysis, renders a machine report, and lists artifacts.
- `qlibx artifact show` exposes one typed envelope by ID without guessing its payload schema.
- Showcase `show_001_basic_real_dw_journey` records the exact reproduction command and writes all
  generated state below its ignored `outputs/` directory.

## Real-data evidence

The sample values are unchanged close-to-base returns for A000660 and A005930 on 2024-01-02 and
2024-01-03 from `data/DW/fng_stock_daily_prices.csv`. Availability uses the confirmed daily close
convention, 15:30 Asia/Seoul. Observation time is normalized to 09:00 Asia/Seoul so the source
session date survives UTC storage. A test independently recalculates all four values from the DW
CSV. The direct Strategy selects A005930 on 2024-01-02; the next-session
two-name information coefficient is 1.0 and is published once for report rendering.

## Trade-offs

This basic journey stops before execution. Daily simulation requires explicit exchange/cost,
instrument, Account, and execution-profile decisions that should not be hidden in a starter sample.
The existing real-DW acceptance suite separately proves that path.

The sample is bundled package data, not a claim that two instruments form a statistically meaningful
research universe. It demonstrates contracts, PIT timing, branching, lineage, and catalog behavior.

## Validation

- Sample real-DW reconciliation, preview/apply/idempotency/conflict, subprocess journey, and
  artifact-show tests -> passed.
- Showcase reproduction command -> passed; A005930 direct/portfolio winner, two stored-signal
  consumers, IC 1.0, and seven catalog artifacts inspected.
- Full pytest -> 81 passed in 58.73s.
- Ruff, import smoke, Git diff check, and uv build -> passed; wheel has six sample files and zero
  intraday runtime entries.
