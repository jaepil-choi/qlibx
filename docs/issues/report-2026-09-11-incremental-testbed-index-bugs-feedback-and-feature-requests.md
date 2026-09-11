# Incremental enhanced-index testbed: its reports sorted into bugs, constructive feedback and feature requests

**Kind: index.** This file is a handoff and carries no finding of its own.

**Status: UNTRIAGED — written by the testbed for the owner, 2026-09-11.**

The testbed (`kwam-enhanced-index/vqapr-incr-testbed`) asked six agents to add one strategy, a
gap-reversal enhanced index on KRX, to an existing project. Three worked in pandas and three in a
vqapr 0.14.4 workspace, with opus 5, sonnet 5 and haiku 4.5. Results are in its
`analysis/RESULT.md`.

In short, opus was exact in both conditions and sonnet with vqapr was exact on NAV. Every vqapr fill
paid exactly 0.03% commission and 0.20% sale tax, with whole shares. vqapr still cost 1.3x to 3.8x
more than pandas, mostly in reading the authoring API.

## Bugs and issues: wrong behaviour or a wrong message

| report | one line |
|---|---|
| `report-2026-09-11-a-decide-after-close-run-is-refused-on-every-friday-and-the-second-refusal-points-at-the-run-end.md` | `within: 1d` refuses every Friday for a 15:31 decision. The second failure repeats the same 403 occurrences with a fix, "widen the run end", that cannot work. The last session's refusal does not name the end that works. |
| `report-2026-09-11-rebalance-of-refuses-a-zero-weight-that-rebalance-signed-keeps.md` | `Rebalance.of` refuses a zero weight that `Rebalance.signed` keeps as flat. The refusal explains sides, not how to hold none. |

## Constructive feedback: behaviour is right, but agents could not see or use it

| report | one line |
|---|---|
| `report-2026-09-11-the-krx-settlement-order-is-not-written-where-an-agent-reads-so-an-agent-reported-vqapr-does-not-apply-it.md` | Sells-first and largest-buy-first are in the code, verified on the momentum record, but in no skill, and the record hides both. An opus agent reported that vqapr does not apply them. |
| `report-2026-09-11-a-decide-after-close-strategy-cannot-log-its-last-fill-from-a-callback.md` | A strategy that logs fill prices from its callbacks loses the last fill. Say where fill-dependent facts come from. |
| `report-2026-09-11-adding-one-strategy-to-an-existing-workspace-still-costs-agents-more-than-a-pandas-project.md` | The measurement: 1.8x (opus), 3.8x (sonnet) and 1.3x (haiku) the pandas cost, with the API-reading breakdown. |

## Feature requests: the two the owner has chosen to build next

| report | one line |
|---|---|
| `report-2026-09-11-feature-request-copyable-strategy-recipes-shipped-with-the-package.md` | Ship copyable recipes: two datasets, positions in memory, an event-log table and the two daily clocks. Emit them with `vqapr new strategy --recipe`. |
| `report-2026-09-11-feature-request-an-export-command-that-writes-a-strategy-record-as-csv.md` | Add `vqapr export` for daily NAV, weights, holdings, fills and custom tables as CSV with numeric columns. |

The testbed will rerun the same six cells after the two feature requests ship. Each request states
the measure it will be judged by.

## Checked and not filed

- **Record tables return some numbers as text.** `analyze-result/references/panels-from-tables.md`
  already documents this. The export request covers the friction it caused.
- **A failed attempt's strategy record stays beside the rerun's.** A reader then asks for
  `strategy_ref`. This is deliberate in `record/reader.py`, and the refusal lists both records.
- **One share of difference between vqapr and the answer key on one day.** It comes from the 1e-12
  weight grid meeting an order of 47.00000043 shares. That is float noise, not a defect.
