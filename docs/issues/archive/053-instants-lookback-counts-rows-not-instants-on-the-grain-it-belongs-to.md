# 053 -- `InstantsLookback` counts rows, not instants, on the one grain it belongs to

**Status:** **CLOSED 2026-09-03** by record `141` (deletion campaign Step 1). The rank is a `dense_rank` over `available_at` inside the name's partition, on rows where the field is non-null, so `n` means instants and every row of an admitted instant comes back; both rows-bound proofs count `DISTINCT` instants the same way. `tests/data/test_lookbacks_follow_grain.py` holds the reproduction (four instants x three rows, `InstantsLookback(2)` -> two instants, six rows). The second finding -- a `rows` grain admits no calendar window -- is **not** closed here and is not an open issue either: it is a ruling to take when a consumer needs it, as the text below says.

**Status when filed:** open. Found 2026-09-03 while taking the `049` measurement
(`experiments/exp_049_the_measurement/`), on `develop @ 724bdadc`.

**Touches:** `data/lookback.py` (`InstantsLookback` docstring), `data/scan.py::observation_rows`
(the ranking clause of the row-wise shape), `data/datasets.py::lookback_fits_grain` (the refusal
text), the scaffold's `--instants-lookback` flavour, `SKILL.md`.

## What was observed

A `grain: rows` registration with three rows per (name, instant) -- one name, four instants, three
account codes -- read with `InstantsLookback(instants=2)` at a cutoff after the fourth instant:

```
n_rows = 2, n_instants = 1
```

Two source rows came back, both from the newest instant. The docstring says *"the last `instants`
observations of each instrument independently ... a name that reports twice a week and one that
reports daily both return `instants` values, from different dates"*, and the refusal a panel grain
emits says *"InstantsLookback counts each name's own instants"*. The SQL counts rows:

```sql
count(<field>) OVER (PARTITION BY instrument ORDER BY available_at DESC, <key fields> DESC
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) <= n
```

On a panel grain -- one row per (name, instant) -- rows and instants coincide, which is why nothing
noticed: that is the grain the ranking was written for, back when it was `RowsLookback`'s meaning.
Record `137` moved the count to `grain: rows` **by name**, and `grain: rows` is exactly the table
where a name has many rows per instant (the vendor's statement warehouse: scopes x settlement types
x account codes x bundles). So the lookback now carries the meaning of a dense per-name count on the
one grain where that count is not what the words say.

## Why it matters

A model on a long table that declares `InstantsLookback(8)` believing it reaches two years of
quarterly statements reaches the newest instant's first eight rows. Nothing refuses it, nothing
reports it; the cross-section is simply missing history, and on a balanced-looking output that is
silent. The `049` harness had to declare `InstantsLookback(2000)` and argue in a docstring that
2,000 rows reach three fiscal years for every name.

A second half of the same finding: a `rows` grain admits **no calendar window** (`lookback_fits_grain`
refuses `CalendarLookback` there). The original `annual-fundamentals` model -- a long vendor table
read back 1,150 days -- is therefore inexpressible on the grain the framework recommends for that
table. Record `137` stated this as a trade-off (*"a calendar window on a long table is a coherent
question the rule does not admit"*); the measurement is the first consumer to hit it.

## What to do

Either the count or the words has to move, and the count is the wrong one to keep: rank by
`dense_rank()` over `available_at` within the name's partition so `n` means instants, and keep the
per-field null-skipping the docstring promises. Whether `CalendarLookback` is admitted on `grain:
rows` is a separate ruling; the measurement's need for it is real and is recorded here rather
than decided here.

## What not to do

Do not fix it by changing the docstring to say "rows". The type exists so that a number cannot
silently mean two things (design 2.4, `docs/issues/archive/033`); making it mean "source rows" on a
grain where the row count per instant is a property of the vendor's layout is the same silence
under a new name.
