# show_006 — ensemble netting over two published members

Two signed views — a five-day price reversal and a ten-day price momentum tilt — each publish their
allocation as an ordinary dataset. A third run, the ensemble, subscribes to both, measures what
combining them implies ticker by ticker, combines them by simple equal weight, and executes the
result on the KRX profile. All three halves are real runs on the public spine.

Reproduce:

```
uv run python showcases/show_006_ensemble_netting/run.py
```

It reads `tests/fixtures/real`, so it runs on a clean checkout with no vendor warehouse.

## What this demonstrates

| Claim | How it is shown |
|---|---|
| A member is a published dataset, not a special reader | Each member's callback evidence goes straight to `publish_run_allocation`, exactly the show_005 path, called twice under two dataset ids |
| The ensemble subscribes to both members through ordinary `DataRequirement`s | `EnsembleStrategy.requirements()` declares `reversal_allocation` and `momentum_allocation`; the run's own `strategy_accesses` (not a static declaration) are checked to prove both were actually read |
| Ticker-level netting is measured, not asserted | `net_members` is called on the two panels every occurrence and the result — `long_weight`, `short_weight`, `offset_weight`, `net_weight` per instrument — is written to a declared recorder table and read back from the run's own output |
| The members genuinely disagreed | At least one ticker on at least one occurrence carries a non-zero `offset_weight`; the run asserts this rather than printing it, and it holds on the committed fixture (11 of 11 overlap occurrences cross zero on this run) |
| One member's memory moved, the other's never did | `reversal` mutates `self.memory` every occurrence; `momentum` never assigns it. The two members' published lineage — computed by the package from committed vs. current model-state refs, not self-reported — carries `state_path == ["moved"]` for `reversal` and `["constant"]` for `momentum` |
| Long-only is emergent | Both members are signed and dollar-neutral. Neither is filtered before combination; the registered `no_short` intersected with `single_name_cap` is what removes the short leg |
| The combination rule is the Strategy's own choice | The ensemble combines the netted per-ticker signal with `equal_weight` and matches its own declared gross-active budget with `rescale`. `net_members` itself never decides a combination — it only measures |
| The bounds are the shipped kit's own | `optimize` is called against the box the strategy builds from `no_short` and `single_name_cap` on the benchmark it subscribes to |
| The account is verified against its own journal | Cash and every position are rebuilt from the committed fill journal and compared to the committed `AccountSnapshot`; a mismatch aborts the run |
| Output is deterministic | The whole pipeline runs twice into separate projects, and both the reported outcome and the SHA-256 artifact digests must match |

## What this does NOT demonstrate

- **No cost model beyond the declared KRX profile.** 3bp commission both sides and 20bp sale tax on
  sells, whole shares, long only. No ticks, price limits, queue position, liquidity or borrow.
- **The members are demonstration signals**, a demeaned five-day reversal and a demeaned ten-day
  momentum tilt, each sized equal-weight and rescaled to a 4% gross active budget. They exist to be
  signed, dollar-neutral, and mutually disagreeing on this fixture — not to be profitable.
- **`net_members` never decides the combination.** It is a pure measurement (implementation record
  010's prohibition on a package-supplied ensemble combination rule stands); the equal-weight
  combination and the rescale target are this showcase's own economic choice, visible in its own
  source.
- **No ex-ante tracking-error or correlation model.** The offset is a per-occurrence, per-ticker
  arithmetic fact about the two published panels; it says nothing about a portfolio-level risk
  measure.
- **Four names are not two hundred.** The fixture is a four-constituent KOSPI 200 slice; the
  benchmark this showcase's cap is defined against is subscribed to by the ensemble only for the
  cap, never as a signal, since this showcase is signal ensembling, not enhanced indexing
  (`show_005` demonstrates the benchmark-relative path).
- **No warm-up trimming.** The reversal member needs six closes and the momentum member eleven;
  earlier occurrences on each agenda decline with `NoDecision` rather than being excluded from the
  callback calendar. The ensemble only nets on occurrences where both members actually published,
  and its own horizon opens on the first day both have a weight on record: before that day its
  first decision would read an empty window, which `vqapr check` refuses
  (`check.lookback.uncovered`) and which `preflight_run` refuses too since record 168.

## Reading the netting evidence

The ensemble declares one recorder table, `ensemble.netting`, and appends one row per instrument on
every occurrence where both members are visible — not just the occurrences that ended in a trade.
Reading that table back after the run is what lets the showcase assert a genuine crossing rather
than infer one from the final combined weight: a net weight of zero is ambiguous by itself (nobody
held the name, or two members cancelled exactly), and `offset_weight` is the number that disambiguates
it. `net_members` computes `offset_weight = min(long_weight, |short_weight|)`, so it is exactly zero
whenever the members agreed on direction and positive only where they genuinely opposed each other.

## Results

Last verified 2026-09-11 against `vqapr-0.15.0`, on the committed April 2026 KRX slice
(22 sessions, 21 member callbacks, 11 ensemble callbacks, 4 instruments).

| Metric | Value |
|---|---|
| reversal occurrences published | 16 |
| momentum occurrences published | 11 |
| ensemble callbacks (from the first day both members published) | 11 |
| reversal state_path | `["moved"]` |
| momentum state_path | `["constant"]` |
| subscribed allocation inputs | `momentum_allocation` + `reversal_allocation` |
| occurrences where a ticker crossed (non-zero offset) | 11 of 11 overlap occurrences |
| max ticker offset_weight observed | 0.04 |
| shipped compliance registered | `no_short`, `single_name_cap` (cap 0.10 above index weight) |
| ensemble rebalances | 9 |
| dealt fills | 14 (whole shares) |
| commission / sale tax | 52,368.75 / 135,429.80 |
| replayed cash == committed cash | 960,679,501.45 |
| final NAV | 1,000,504,501.45 (from 1,000,000,000) |
| any short position marked | False |

Both members share the same four-instrument universe and the same closing prices; the reversal
member needs a six-close window (five-session return) and the momentum member needs an
eleven-close window (ten-session return), so momentum starts publishing five sessions later on this
fixture. Only the occurrences where both are visible feed the ensemble's netting measurement and its
rebalances; the fixture's 21-session KRX slice yields 11 such overlap occurrences here.

`outputs/` is gitignored, and each replicate builds its own project under it.
