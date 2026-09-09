# The tables a run records, and which question each answers

Every run records three tables, plus any the strategy **declared and then formed** — a table must
come back from `StrategyModel.tables()` as a `TableSpec` before `decide()` may write to it through
`self.recorder`, and writing to an undeclared one refuses mid-run.

Prefer the report over these. Reach for a table when the question is about one row.

## `vqapr.account` — the book over time

`instrument` (`_ACCOUNT` on the cash and NAV row), `account_version`, `cash`, `quantity`, `price`,
`nav`, `observed_at`.

`observed_at` is declared by this table alone and is **not** the envelope's `event_time`: one is
when the fact was seen, the other when it happened.

`--instrument _ACCOUNT` on this table is the strategy's NAV series.

## `vqapr.fill` — what was traded and what it cost

`instrument`, `kind`, `requested_quantity`, `dealt_quantity` (negative on a sale), `price`,
`commission`, `tax`, `cash_delta`, `reason`, `account_version`.

**This is the table cost questions are asked of.** Commission and tax are per fill and per side, so
a category's true cost is a sum over this table — not a rate read off a venue.

`kind` is what the **roster** said. What the fill was **charged** as comes from the venue's own
terms. Those are two statements and nothing compares them, so a venue's declared categories and
the registered roster have to be kept in step by hand. Every filled id was declared — a run
refuses to start without a roster and fails on an order for an undeclared id — so `kind` is never
null in a record written since the two-clocks campaign.

## `vqapr.weight` — the intended allocation

`instrument`, `weight`. Per evaluation, **before execution**. Comparing it with `vqapr.account` is
what `intent.gap` does.

## `vqapr.monitoring` — what each constraint measured

Present when the strategy declared constraints. `constraint`, `passed` (the author's own
comparison), `measured`, `bound`, `excess`, `verdict` (the framework's: `held`,
`within_tolerance`, `breached`), `tolerance`, `offenders` (breaching instrument ids,
space-separated), `account_version`. `event_time` is the fill instant the book was committed and
judged at.

**This is the table compliance questions are asked of.** The strategy record's `contract` block
only counts; which name breached which limit by how much is here, one row per constraint per
commit.

## The five fields every row carries

`run_id`, `producer_id`, `stage`, `event_time`, `sequence` — which run wrote it, what wrote it, at
what point, when the fact happened, in what order. A table cannot declare one of these as a column
of its own.

## `--no-account-positions`

`vqapr run <run-id> --no-account-positions` records only the `_ACCOUNT` row at each valuation
instead of one row per held instrument. Fills are recorded either way — so cost and turnover
survive, and `book` exposure does not.
