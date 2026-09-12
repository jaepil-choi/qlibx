# 039 — Two questions about a quantity, and a fingerprint that tells the truth

## Why this exists

Both defects were found the same way: by diffing the two shipped profiles against each other after
`TradeRule` absorbed their differences (record 038). What was left should have been identical, and
was not.

### 1. A divisible instrument never checked its own minimum

The two profiles spelled the same check differently. KRX compared a quantity against its own
`quantize` round-trip:

```python
if quantity != rule.quantize(quantity):   # refuse
```

`quantize` returns a fractional quantity **unchanged** when the instrument is divisible, so the
round-trip always matched and `minimum_quantity` was never consulted. Measured on a listing
declaring `minimum_quantity=0.1`:

```text
academic spelling (q < minimum)      -> refuse 0.05: True
krx spelling      (q != quantize(q)) -> refuse 0.05: False    <- accepts below its own floor
```

KRX itself was safe only because its constructor forbids fractional listings, so the path was
unreachable *on that venue*. Any venue reusing the shorter spelling with a divisible instrument
would silently accept orders under its declared minimum. This is precisely the drift
`docs/issues/archive/002` predicted from duplicated validation.

### 2. A venue-specific field would not have reached the fingerprint

`TradeRule.declaration_identity` listed the base fields by hand. A venue regime declared on a
subclass — a price-limit rate, a lot-unit convention — would not appear, so the workspace would
treat two materially different declarations as the same one and reuse a frozen component across a
rate change. This had to be fixed **before** subclasses exist, not after, because the failure is
silent reuse rather than an error.

## What changed

**`TradeRule.permits_quantity(quantity)`** is the one spelling both profiles now call. It asks the
two questions separately, because they are separate:

```text
minimum_quantity  the smallest size the venue accepts at all
quantity_step     the unit sizes land on, when the instrument is not divisible
```

A divisible instrument returns `True` for any size at or above the minimum — it declares its own
divisibility, so it is on its unit by definition. `_is_step_aligned` in `venue.py` is deleted; it
had no other caller.

**`declaration_identity` collects subclass fields automatically:**

```python
return (type(self).__name__, ..., self._extra_identity())

def _extra_identity(self):
    return tuple((name, str(getattr(self, name)))
                 for name in self.__dataclass_fields__ if name not in _BASE_RULE_FIELDS)
```

Reading `__dataclass_fields__` rather than a hand-kept list means **adding a field cannot forget to
extend the identity**. The type name is included too, so a subclass that adds nothing is still a
different declaration from the base.

Verified across the four states a regime field can be in:

```text
base                      (..., ())
rate = 0.30               (..., (('price_limit_rate', '0.30'),))
rate = 0.10               differs from 0.30
rate = None  (switched off)  differs from both, and from base
```

The last one matters for the capability toggle this is groundwork for: **an explicitly disabled
regime is not the same declaration as a venue that has no regime at all**, and a run record can say
which it was.

## Why a typed subclass rather than a free-form dictionary

This was decided deliberately, against the simpler-looking option. A price limit is a percentage in
Korea (±30%) and China (±10/20%) but a **fixed band table** in Japan (¥1,000–1,500 → ±¥300), and a
same-day resale ban exists only in China. Those are different *shapes*, not different values, so a
single shared field cannot hold them.

Between `extras: dict` and a subclass, the deciding argument is when a mistake surfaces:

| | misspelled key | switched off |
|---|---|---|
| `extras` dict | `KeyError` mid-run, or silently wrong | indistinguishable from forgotten |
| typed subclass | `TypeError` at venue construction | `= None`, and it is in the fingerprint |

The framework's standing rule is fast explicit failure over a guessed schema, and the toggle
requirement makes "off" a state that has to be *recorded*, which an absent dictionary key cannot do.

## Trade-offs

**`permits_quantity` takes an absolute size and returns `False` for a negative one** rather than
raising. Callers already take `abs(...)` before the check, and a signed value reaching it is a
caller bug that shows up as a refused order rather than a crash mid-batch. The alternative — raising
— would make the two profiles' error surfaces diverge again.

**`declaration_identity` now includes the class name**, so renaming a rule class changes every
fingerprint that uses it. That is correct (a different type is a different declaration) but it means
a pure rename invalidates frozen components, which is a real cost at refactor time.

## Validation

- `uv run pytest -q` — **630 passed**; `uv run ruff check src tests` clean.
- **Both fixes discriminate.** Reverting the minimum check fails 2 tests
  (`test_minimum_quantity_is_checked_even_when_the_instrument_is_divisible` and
  `test_both_profiles_refuse_the_same_undersized_order`); reverting the identity change fails the
  other 2. Restored, 6/6 pass.
- The two profiles are proved to refuse the same undersized order through their real `execute`
  paths, so the drift that produced this cannot recur without a test failing.
