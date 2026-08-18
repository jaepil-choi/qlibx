# 013 — A halt the Strategy could not predict does not stop a rebalance

## Why this exists

Record 012 shipped a mistake and this corrects it.

`optimize()` had been made to **refuse** when a frozen holding sat outside its declared box, on the
reading that Architecture 5.3's `s.t.` block is a conjunction. That reading missed the paragraph
that governs it (`architecture.md:1553`):

> 거래 불가 종목의 `w_j = w⁰_j` 고정은 제약이 아니다. compliance가 아니라 전략이 등록 dataset에서
> 읽은 시장 사실이고, `optimize`의 별도 인자로 남는다. 섞으면 *"제약을 위반했다"*와
> *"거래할 수 없었다"*가 같은 finding으로 나온다.

Refusing turned "could not trade" into "violated a constraint" — exactly the conflation canon
forbids — and let one untradable name stop an entire rebalance.

## The deeper correction

Removing the refusal exposed the real point: **the Strategy should not be freezing for a halt at
all.** Tradability is an execution-time fact. At the callback the Strategy cannot know whether a
name will be halted at the fill, so freezing for it is guessing.

The correct loop, now demonstrated end to end:

1. The Strategy keeps targeting the weight it wants, every session, including a name that turns out
   to be halted.
2. The intent carries the **target**, which is inside the cap, so it passes the constraint boundary.
3. The venue refuses the fill with `ZeroDealtReason.NONTRADABLE`.
4. The position stays put; the rest of the book trades normally.
5. Monitoring reports the resulting breach against the committed account.
6. The next occurrence tries again, and resolves it once the halt lifts.

No engine change was needed for this. The behaviour was already correct; the showcase had been
constructing an artificial freeze that the engine was never meant to receive.

## What changed

- `optimize()` no longer refuses a frozen holding outside its box. It honours the holding, still
  balances the budget, and reports the name in `OptimizeResult.frozen_outside_box` as a diagnostic.
- `ZeroDealtReason` joins the public surface. A user reading a backtest has to be able to tell
  "refused because halted" from "no order was needed".
- The showcase halts one name for six sessions and asserts the loop: exactly six `NONTRADABLE`
  refusals for that name, the rest of the book still trading, and the run completing.
- The README's previous "Known gap" section is deleted. It described a limitation that does not
  exist, produced by misusing `frozen`.

## Trade-offs

**`frozen` keeps its narrow meaning.** It is for a holding the Strategy genuinely knows it must
carry, not for guessing at halts. Splitting it into `frozen` versus `pinned` was considered and not
built: there is one use, so there is one concept.

**The diagnostic is not a finding.** `frozen_outside_box` is optimizer output, not a
`ConstraintFinding`. Monitoring remains the objective judge and reads the committed account, which
is what keeps the two failure modes distinguishable.

## Validation

- `uv run pytest -q` — 299 passed. Ruff check and format clean. Package imports.
- `uv run python showcases/show_005_enhanced_index/run.py` — six halted sessions produce exactly six
  refused fills for that name, dealt fills drop from 67 to 62, the run completes, the fill journal
  still replays to the committed Account exactly, and two clean runs agree on their manifests.
