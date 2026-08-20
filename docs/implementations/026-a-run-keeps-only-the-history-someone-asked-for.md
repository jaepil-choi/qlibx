# A run keeps only the history someone asked for

## Why this exists

Canon §4.3 and §7.3 declare `account_history(requirement)` on the callback surface, and §7.3 gives
the reason: `UC-ACCOUNT-HISTORY-001` requires that stop-loss and cooldown be expressible **without
Strategy state**, because a rule built on `memory` cannot be used by a research-only Strategy.

`src/vqapr/account/history.py` was 0 bytes. `HistoryRequirement`, `AccountHistory` and
`account_history()` appeared nowhere in the source. A Strategy callback received an
`AccountSnapshot` — version, cash, quantities — and nothing else. **Neither stop-loss rule was
writable**, not because the data was missing but because no path reached it.

Meanwhile the data was not only present but expensive. `mark_history` grew for the life of a run
and only `latest_mark` was ever read: roughly **210 MB resident at 2,500 sessions × 500 names**,
carried by every run whether or not anything looked at it.

Both facts have the same fix. The declaration that says what a Strategy reads is also the
declaration that says what the run keeps.

## What changed

### `AccountRequirement` — declared like data, because it is the same thing

```python
AccountRequirement.of("stop", fields=("nav",), lookback=RowsLookback(4))
```

It reuses `RowsLookback`, so there is one lookback vocabulary to learn rather than two.

**No `dataset_id`.** A run has exactly one account; there is nothing to select.

**No `scope`.** The field names carry it — `nav` exists once per instant, `quantity` exists per
instrument. A `scope` argument would make `fields=("nav",), scope=INSTRUMENT` expressible, and a
contradiction that cannot be written is better than one that is validated.

**`lookback` is required.** An optional lookback is an unbounded read, which is O(history) per
callback and therefore quadratic per run — the exact cost shape records 021–023 removed from the
hot path. Measured on 2,000 held marks: full projection 0.0403 ms, bounded tail 0.0003 ms, and the
bounded one does not grow.

Fields are fixed:

```
account series     nav, cash
instrument panel   quantity, price, observed_at
```

All five are values `commit` and `mark` already computed, so history performs no arithmetic of its
own and cannot disagree with the account it describes. `realized_pnl` and `avg_entry_price` are
deliberately absent: both depend on a cost-basis convention (FIFO, LIFO, weighted average) that is
a tax and jurisdiction question, and choosing one would make the package impose an accounting
policy. They are derivable from the journal by whoever picks the convention.

**`price` and `observed_at` are separate fields, not a pair.** A Strategy that only needs the price
should not pay to retain when it was observed. This is what a field means in `DataRequirement` too.

### Retention follows the declaration

`Account(retained_marks=N)` where `N = max(declared lookback)`, defaulting to **1**.

| declared | resident |
|---|---|
| nothing | 1 mark — **210 MB → 84 KB** |
| `nav`, lookback 4 | 4 marks |

A Strategy that never looks at its own path now costs nothing to carry one. That is the point: a
run must not pay for a capability it does not use.

The two `Prepared*` invariants that asserted `next.mark_history[:-1] == source.mark_history` became
a tail comparison. Marks falling off the front is the retention policy working; a mark being
altered, reordered or dropped from the middle is still refused.

### Full history moves to the recorder

Retention makes memory a bad place to reconstruct a run from, so `vqapr.account` — already a
package-owned default table — now publishes the whole record:

```
instrument, cash, nav, quantity, price, observed_at, account_version
```

One account-level row plus one row per held instrument, per occurrence. The recorder streams to
parquet rather than holding rows resident (record 022), so this costs publication, not memory.

The table records the **committed** mark, not a live one — a callback reports the account it saw
before deciding, which is why the series sits one commit behind the callback that writes it.

### The proof got stronger, not weaker

`show_007` verified rehydration by comparing published parquet against the in-memory
`mark_history`. With retention that comparison cannot hold, and the failure was the design telling
the truth: **memory was never the right authority for post-mortem.**

It now rebuilds marks from the published table alone and checks them against the one mark the
account still holds. The result:

```
rehydrated from publication : 60 marks
retained in memory          :  4 marks
```

The assertion flipped from `rehydrated <= committed` to `rehydrated >= committed`, plus a check
that more than one version is reconstructable. The proposition moved from *"does this match the
running object"* to *"can this be rebuilt from what was published"*, which is the one post-mortem
actually depends on.

## What this makes possible

```python
class StopLoss(StrategyModel):
    def account_requirements(self):
        return (AccountRequirement.of("stop", fields=("nav",), lookback=RowsLookback(4)),)

    def on_occurrence(self, context):
        navs = context.account_history.series("nav")
        if len(navs) == 4 and all(b < a for a, b in zip(navs, navs[1:])):
            return self._flatten(context)
```

Per-name is `panel("price")`. Verified:

```
rule 1  navs=[100,99,98,97]  -> flatten True      navs=[100,99,98,101] -> flatten False
rule 2  DOWN 10→9→8→7 stopped    UP 10→11→12→13    HALT 10→10→10→10 not stopped
```

**`HALT` is why `observed_at` is its own field.** Its price is flat for four sessions, but its
`observed_at` never moves — nobody quoted it. Without that column a Strategy reads a halt as a flat
market, or worse, a carried price as a real one. Reading an undeclared field raises rather than
returning empty, so a missing declaration fails loudly instead of quietly disabling the rule that
depended on it.

## Trade-offs

- **A rule can only see as far back as it declared.** That is the constraint that keeps the read
  bounded, and it is checked before the run starts rather than during it.
- **The published account table is wider**, one row per held instrument per occurrence instead of
  one row per occurrence. That is the cost of making a run reconstructable without holding it in
  memory, and parquet is where that cost belongs.
- **`fill_history` is untouched.** Six showcases replay it to verify account arithmetic, so giving
  it the same treatment means rewriting all six. It has the same unbounded-growth shape and is a
  separate piece of work.

## Validation

```
uv run pytest -q      529 passed   (527 before)
uv run ruff check     clean
```

`tests/flow/test_publish_run_record.py::test_the_defaults_need_no_declaration` previously asserted
no default field contains "nav", with a correct reason: a callback has no marks of its own, so
claiming a NAV would be a wrong number under a true-sounding name. Recording the *committed* mark
makes the claim true, and the test now pins the full field set with that reasoning written down.
