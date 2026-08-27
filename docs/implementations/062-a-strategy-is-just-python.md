# A strategy is just Python

## Why this exists

The scaffold `vqapr new strategy` emitted was **111 lines**, and the reason it was long is the
reason it was wrong. To return a decision, the author had to write this:

```python
return EconomicPortfolioIntent(
    uuid5(NAMESPACE_URL, f"{STRATEGY_ID}/{context.occurrence.occurrence_id}"),
    STRATEGY_ID,
    targets,
    Decimal(1) - weight * Decimal(len(selected)),
    BUDGET,
    _source_refs(context),      # a helper that reassembled provenance from window.accesses
    context.account.version,
    None,
)
```

Nine positional arguments, of which the author genuinely chose two. The intent id, the provenance
refs and the account version all have exactly one correct value, all are derivable from the context
the framework already holds — and the Flow **recomputes every one of them and refuses the intent if
the author's version disagrees**. Work that can only be done one way, checked by the thing that
asked for it.

The weights were worse. `sum(target_weights) + cash_weight == 1` is enforced exactly, so the author
had to make their numbers land on one to the last digit. A single-ulp miss is refused by the same
invariant that catches a real mistake.

## What changed

**`Rebalance.of(long=..., short=...)`** takes relative conviction. The author says which names they
like and how much they like them *relative to each other*; normalising each side, splitting the
invested fraction, rounding onto the canonical grid and balancing against cash is arithmetic with
one right answer.

The rounding residual settles on the largest position rather than in cash. Cash looks like the
natural place — it is the line nobody expressed a view about — and it is the wrong one, because it
is also the line with a hard bound; see the defects below.

A side is chosen by **which mapping a name appears in**, never by sign: `short={"A": 2}` means twice
as short. Accepting `short={"A": -2}` would give one intention two spellings that disagree, so a
negative conviction is refused. The budget follows from what was asked for — passing a short book
implies `SIGNED` — rather than being declared a second time and able to contradict the weights.

**`register strategy <id> <file.py>`** registers a component by naming it. The YAML wrapper around a
component contained exactly the three facts now on that command line. Datasets, sources and agendas
stay in the declaration, because those *are* declarations — there is no code to point at.

The sole-subclass check parses rather than imports, so "this file has two strategies" is refused as
that, with **the count and the names**, rather than surfacing as whatever an ambiguous import
happens to say. Zero and two are different mistakes with different repairs (AC-A4).

**`StrategyResult`** defaults `next_state` and `diagnostics`. Most strategies carry no
cross-callback state, and requiring `next_state=None, diagnostics={}` on every return taxed every
author for the uncommon case. A strategy that *does* carry state still has to say so, which is what
keeps the cadence rule replayable.

## The result

38 lines, and the only line that matters is marked:

```python
# THE SIGNAL. Momentum: recent gain wins. Flip the sign for reversal.
scores[instrument] = values[-1] / values[0] - 1
```

## Two arithmetic defects, found by running the awkward cases

The first version of `Rebalance.of` passed every case I reasoned about and failed two I did not.

**The rounding crumb was settled in cash.** Three shorts at `-0.5/3` do not divide evenly and leave
`-1e-12`. That pushed cash to `1.000000000001` — one step past fully-uninvested — and a book that
is arithmetically perfect was refused for a rounding artifact. Cash looked like the right place for
the residual because it is the line nobody expressed a view about; it is the wrong place because it
is also the line with a hard bound at 1. The crumb now lands on the largest position, where it is
proportionally smallest and cannot move cash across a bound.

**Cash was computed as `1 - invested`, which is wrong for a signed book.** `invested` is *gross*
exposure; `sum(weights)` is *net*. A dollar-neutral long/short book is fully invested and nets to
zero, so `1 - invested` produced a residual of about 1 — not a crumb, an entire portfolio. Cash is
the net residual. Those are different numbers and only one of them is cash.

Both are now covered by a parametrized case list over inputs that do not divide evenly, and both
are mutation-proved: reverting to the cash-absorbs-residual form fails exactly the uneven
long/short cases.

## A verification mistake worth recording

I first reported AC-A3 as proven end to end: `check: ok`, `run: 2932 occurrences`. It was not.

The scaffold had been registered under the sample's own strategy id, where `install` had already
registered a component — so the registration was correctly **refused as a conflict**, and the run
that followed executed the *sample's* strategy while I read the green result as proof of mine.

The tell was available and I did not look: `register` had exited 1. The fix is a fresh component id
with its own agenda and its own config, so the run can only be executing the scaffold — confirmed
by asserting the workspace holds the scaffold's path before the run, and by the account version
landing on 674 rather than the sample's 729.

That assertion is now in the test, because the failure mode is silent: a green end-to-end run that
proves nothing is indistinguishable from one that proves everything.

## Validation

```
uv run --no-sync pytest -q                                   # 1,266 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH 2096 / 97 / 110919; value gate exact, weight digests byte-identical to the Step 0
capture. The plan flags this step as able to move weight values, so both gates were mandatory; the
authoring rewrite is parity-inert.

AC-A1 (≤40 lines), AC-A2 (no `uuid5`/`source_refs`/`account_version`/`strategy_id`), AC-A4 (count
in both refusals) and AC-A6 (no `rescale`, no `QUANTUM`) are pinned as tests and mutation-proved —
re-introducing `uuid5` fails the parametrized case that names it.

End to end, an agent typing four commands and editing nothing:

```
vqapr new strategy alpha --dataset sample-prices --lookback 2   ->  38 lines
vqapr register strategy alpha alpha.py                          ->  ok, class Alpha
vqapr check spec.yaml                                           ->  ok: true, 0 failures
vqapr run spec.yaml                                             ->  2,932 occurrences, account 674
```
