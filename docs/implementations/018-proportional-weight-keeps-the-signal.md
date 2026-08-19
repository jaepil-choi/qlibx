# 018 — `proportional_weight` scales the signal instead of replacing it

## Why this exists

`proportional_weight(signal, sizes)` sized each name by the panel entry and took only the **sign**
from the signal:

```python
sized = {
    instrument: magnitudes[instrument].copy_sign(value) if value != 0 else Decimal(0)
    for instrument, value in checked.items()
}
```

`copy_sign` discards the signal's magnitude. Record 014 wrote that down as a deliberate rule —
"all three take the **sign from the signal**" — so the behaviour matched its own documentation.
The documentation was the mistake.

## What the algebra showed

With a uniform panel the three sizing functions should stay distinguishable. They did not:

```
signal = {A: 3, B: -1, C: 1},  sizes = {A: 100, B: 100, C: 100}

현재 proportional : {A:+0.3333, B:-0.3333, C:+0.3333}
signal*size       : {A:+0.6000, B:-0.2000, C:+0.2000}
signal_weight     : {A:+0.6000, B:-0.2000, C:+0.2000}
equal_weight      : {A:+0.3333, B:-0.3333, C:+0.3333}

현재 == equal_weight ?           True
signal*size == signal_weight ?   True
```

The old `proportional_weight` **is** `equal_weight` whenever the panel is uniform, so it was a
second spelling of a function that already existed. `signal × size` reduces to `signal_weight`
instead, which is what a panel-scaled sizing rule should do: the panel scales the strength, it
does not replace it.

Nothing is lost. Direction-only sizing is still expressible, by saying so:

```
현재 proportional(sig, size)      : {A:+0.6667, B:-0.2222, C:+0.1111}
신규 proportional(sign(sig), size): {A:+0.6667, B:-0.2222, C:+0.1111}
동일? True
```

## Why it mattered in practice

`vqapr-testbed/` needed the report's "점수 크기에 비례해 배분" — size by score magnitude — and
`proportional_weight` looked like the built-in for it. It was not, so the testbed hand-rolled the
multiplication. A built-in that quietly means something else than its name is worse than a missing
one: the caller writes their own and the framework's purpose is defeated.

## What changed

- `proportional_weight` computes `signal × size` and normalises to gross one.
- The module docstring now states the relationship: `proportional_weight` is `signal_weight` with
  a panel and reduces to it on a uniform panel; `equal_weight` is the one that discards strength.
- Three tests pin the new contract: strength is proportional, a uniform panel reproduces
  `signal_weight`, and a sign-reduced signal reproduces the old direction-only behaviour.
- Record 014's "all three take the sign from the signal" line is superseded by this record.

## Validation

- `uv run pytest -q` — 510 passed.
- `uv run ruff check src tests` — clean.
- No showcase called `proportional_weight`; `show_005_enhanced_index` and
  `show_008_alpha_family_ensemble` regenerate to byte-identical manifests, so nothing downstream
  moved.
