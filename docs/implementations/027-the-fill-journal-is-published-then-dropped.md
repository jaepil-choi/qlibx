# The fill journal is published, then dropped

## Why this exists

Record 026 bounded `mark_history` to what a consumer declared it would read. `fill_history` was
left with the same unbounded shape: every journal entry a run ever committed, held for the life of
the run, read by nothing inside `src/`.

Its only consumers were six showcases replaying account arithmetic after the run finished — the
check that cash and positions rebuilt from the journal equal what the Account committed. A run
carried its entire trade history in memory so that a verification could read it once at the end.

That verification is worth keeping. Holding the journal resident to serve it is not.

## What changed

### `vqapr.fill` — a package-owned record of every committed fill

```
instrument, account_version, requested_quantity, dealt_quantity,
price, cash_delta, commission, tax, reason
```

Written by `prepare_account_commit` from the journal entries the Account just committed, as a
recorder chunk. The Account then keeps only those entries, so `fill_history` stops growing.

**This does not open the door canon §9.1 closes.** That rule forbids a *free-form* recorder at the
execution stage, and its reason is stated plainly: two ways to express the same fact leaves a
reader not knowing which to trust. This is one fixed schema the package writes itself, from values
the Account already committed — the same standing as `vqapr.weight` and `vqapr.account`. No
recorder is handed to execution code, and no Strategy declares this table.

**Zero-dealt fills are recorded, not filtered.** A refusal is a market fact the run has to be able
to show afterwards, so it is published with its reason.

### Retention

| | before | after |
|---|---|---|
| `fill_history` | every entry of the run | the last commit's entries |
| `mark_history` | every mark | as declared (record 026) |

Measured on `show_005_enhanced_index`:

```
peak fill_history resident :  4      (the last commit)
peak mark_history resident :  1      (nothing declared)
fill rows published        : 84      (all of them)
```

### The six showcases replay from the record

Each one iterated `account.fill_history`. They now iterate the published `vqapr.fill` rows through
a small `_recorded_fills(result)` helper, reading string-encoded decimals back the same way every
other published table is read.

**The proof got stronger.** Replaying a live object against itself shows the object is
self-consistent. Replaying the *published record* shows the artifact reconstructs the account,
which is what someone reading the run afterwards actually depends on. `show_005` still reports:

```
replayed == committed : 516418870.53000000 == 516418870.53000000
```

`show_004` needed one extra change: it summed `fill.notional`, which is derived. The record carries
its two factors, so the showcase multiplies them.

## Trade-offs

- **Fill provenance now requires the publication.** A run that is never published keeps only its
  last commit's entries. That is the intended direction — evidence belongs in artifacts, not in
  the object that produced them — but it does mean an in-process caller cannot reach back for the
  whole journal.
- **The published table is one row per fill including refusals**, which is larger than the account
  table. That is what makes it sufficient to rebuild the account, and parquet is where that cost
  belongs.
- `PreparedAccountTransition` now checks that a committed state carries *exactly* the entries its
  own commit produced, rather than that it extends the previous history. Entries falling away is
  the retention policy; entries being altered or invented is still refused.

## Validation

```
uv run pytest -q      529 passed
uv run ruff check     clean
showcases             8/8 run
```

All eight showcases were run rather than only the three covered by tests, because the five without
test coverage are exactly where an unnoticed break would sit.
