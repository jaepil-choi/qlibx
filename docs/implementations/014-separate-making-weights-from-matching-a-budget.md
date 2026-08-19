# 014 — Separate making weights from matching a budget

## Why this exists

`portfolio/weighting.py` was declared in canon and shipped empty, so every Strategy had to build its
own weights inline. The three functions canon names — `signal_weight`, `equal_weight`,
`proportional_weight` — now exist, plus one canon did not have.

## The decision that shaped it

PRD 5.5 is blunt about budgets:

> budget을 weight를 만드는 연산이 스스로 결정하지 않는다. 선언된 예산보다 적게 배분된 결과를 연산이
> 자동으로 채우면 flexible을 fixed로 몰래 바꾸는 것이므로 금지한다.

A **fixed** budget fills what it declared; a **flexible** one leaves the rest in cash when the signal
is weak. Both are correct answers and the package must not silently convert one into the other.

A sizing function that normalised to a declared budget would do exactly that conversion. So making
and matching are separate calls:

```python
raw = signal_weight(signal)                  # sign from the signal, ratios exact
w   = rescale(raw, long=1, short=-1)         # fixed budget: dollar neutral
w   = raw                                    # flexible budget: nothing filled in
```

Which one a Strategy chose is visible in its own source, which is the distinction PRD 5.5 asks for.

Canon carried a second gap: its signature table gave every sizing function a `cash_range`, but a
dollar-neutral book cannot be expressed in cash. Long 1 / short −1 and long 0.5 / short −0.5 both
satisfy `sum(w) = 0, cash = 1`. `rescale(long, short)` sizes each side directly, and cash stays what
it already was — `optimize`'s decision variable. Architecture 5.3 was amended before this code was
written.

## What each function guarantees

`signal_weight` sizes by `|signal|`, `equal_weight` sizes every selected name the same, and
`proportional_weight` sizes by a supplied magnitude panel. All three take the **sign from the
signal** and return gross one.

> **Superseded by record 018.** "All three take the sign from the signal" was read as *only* the
> sign, and `proportional_weight` was built that way — which made it identical to `equal_weight`
> whenever the panel was uniform. It now scales the signal's strength by the panel.

Two guarantees cannot both be exact when a division does not terminate, so they are split
deliberately:

- **Sizing keeps the ratios exact.** `equal_weight` really does return equal weights; three names
  each get `1/3`, whose gross is one to the precision a Decimal holds.
- **`rescale` keeps the declared total exact.** Asking for a long side of one gets exactly one, with
  the residual settled onto the largest member of that side, ties broken by name so the result is
  order independent. PRD 5.5 treats a declared budget that does not match the actual weights as a
  failure, so the declaration wins there.

## Trade-offs

**`rescale` matches, it never invents.** Asking for a long side out of a book with no longs is
refused. So is asking for a zero short side out of a book that holds shorts — that deletes positions
rather than resizing them, and dropping a position is a decision the Strategy has to make itself.

**`equal_weight` does not select a zero signal; `signal_weight` carries it at zero.** Equal weighting
means equal among the names you picked, and a zero signal is not a pick. Sizing by signal strength,
on the other hand, keeps the name visible at zero so the universe stays readable.

**A magnitude panel carries no direction.** `proportional_weight` refuses a non-positive size rather
than reading a sign from it, because a negative size beside a signed signal makes the direction
ambiguous.

## Validation

- `uv run pytest -q` — 322 passed (from 299). Ruff check and format clean, package imports, sdist
  and wheel build, showcase unchanged and deterministic.
- Twenty-three focused tests, including the real committed closes used as a magnitude panel, and
  purity checked by calling twice and confirming the caller's mapping is untouched.
