# 019 — A mark says when its price was observed

## Why this exists

`SelectedMark` carried `(instrument_id, price)` and its docstring claimed "no prior-price fallback
exists". Both were wrong about what the framework actually does.

The mark query uses `RowsLookback(1)`, which returns the newest row **at or before** the cutoff.
For an instrument that stopped trading, that row is simply older. Measured:

```
cutoff = 2024-01-10  (HALT stops appearing after 2024-01-04)
  HALT  close=203.0000  available_at=2024-01-04
  LIVE  close=109.0000  available_at=2024-01-10
```

So the previous close was already being used — a halted position was already carried at its last
price rather than written down, which is the correct behaviour. What was missing is that
`_marks_for_occurrence` built a `{instrument: price}` mapping and **discarded the `available_at`
it had just read**. The evidence therefore could not say whether a mark was current, and the
staleness of a book was not reconstructable from what a run recorded.

## The decision

Valuation records a fact and makes no judgement.

A three-month halt and a delisting are identical at the cutoff. They are told apart only by
whether the instrument trades again, which is a fact from the future that valuation does not
have. Any attempt to classify at valuation time would either guess or need to look forward.

So the split is:

| layer | states | kind |
|---|---|---|
| valuation | which price was used, and when it was observed | **fact** |
| reporting | that the gap is N sessions, and whether trading resumed | **judgement** |

This matches how the venue already reports `ABSENT` and `NONTRADABLE` as typed market facts and
leaves their interpretation alone.

## What changed

- `SelectedMark` gains a required `observed_at`, validated tz-aware, plus `staleness(cutoff)`
  returning the gap as a `timedelta`. The value is a fact and not a verdict: it says the price is
  older, not why.
- `_marks_for_occurrence` returns `tuple[SelectedMark, ...]` carrying each row's own
  `available_at`, instead of a mapping that dropped it. When several rows arrive for one
  instrument the newest observation wins.
- The docstring claiming no fallback exists is replaced by a description of what the lookback
  actually does and why the observation instant is recorded.

## Trade-offs

**A delisted holding stays in NAV at a price that never updates again.** That is the honest
outcome: the money is genuinely tied up in a position that cannot be sold, and every later weight
is allocated around it. Writing it to zero would report a loss that did not occur, and dropping it
would lose the position entirely.

**Staleness is not surfaced as a warning.** A run does not fail or flag on an old mark, because
"old" is not an error — it is Tuesday for a halted name. The information is in the evidence for
whoever asks later.

## Validation

- `uv run pytest -q` — 515 passed, including four new tests pinning that a halted holding keeps
  its last price, reports its staleness, still contributes to NAV, and refuses a naive timestamp.
- `uv run ruff check src tests` — clean.
- `show_005_enhanced_index` and `show_008_alpha_family_ensemble` regenerate byte-identical
  manifests, so no priced path moved.
