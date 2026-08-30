# 017 — The run-spec template offers an account mode that does not exist

**Status:** template half **closed** by
`docs/implementations/091-the-template-offers-modes-that-exist.md` (branch
`fix/017-template-account-mode`) - the offered list is now derived from `AccountMode` rather than
restated, so it cannot drift again. The message half (a mistyped closed-set enum surfacing as a
`KeyError` repr instead of the permitted set) is `fix/017-closed-set-refusal`, tracked separately.

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-005**,
severity `slowed` for this reporter and *"`blocked` for a first-time user without the enum already
on screen"*.
**Touches:** `src/vqapr/cli/new.py:216`, and the `run.check.declaration_invalid` failure path.

## What the template says

`vqapr new run-spec` emits, with a comment that reads as a closed set of exactly two:

```yaml
initial_account:
  cash: "1000000"              # quoted to preserve precision (parsed as Decimal)
  mode: LONG_ONLY              # LONG_ONLY or LONG_SHORT
```

The book was long/short, so the reporter took the value the template offered.

## What happens

```json
{"code": "run.check.declaration_invalid",
 "explain": "declaration-shape",
 "fix": "correct the run spec at declarations\spec.yaml so the declaration phase completes, then check again",
 "observed": "KeyError: 'LONG_SHORT'",
 "requirement": "the spec must resolve against what the workspace has registered",
 "source": {"file": "declarations\spec.yaml", "key_path": null, "line": null}}
```

The real enum is `AccountMode`, whose members are `LONG_ONLY` and **`SIGNED`**. There is no
`LONG_SHORT` anywhere in the package — confirmed here: `grep -rn LONG_SHORT src/` returns exactly
one hit, `cli/new.py:216`, the comment itself.

## Three failures at once, each separately worth fixing

1. **The template emits a value the package rejects.** This is the one scaffold line most likely to
   be copied verbatim, precisely because it reads as a closed set of two.
2. **The diagnostic is a raw `KeyError` in `observed`.** The journey's note: *"Every other refusal I
   have seen from this package is a sentence; this one is a Python exception repr that happens to
   name the offending token only because the token is the dict key."*
3. **`requirement` and `fix` both describe the wrong problem.** `requirement` says *"the spec must
   resolve against what the workspace has registered"* — nothing about the workspace is involved,
   and the reporter ran `vqapr list` before doubting the template. `fix` says to correct the spec so
   the phase completes, which is a restatement of "it failed".

The skill's own `declaration-shape` recovery section promises the opposite of what arrived:

> When a value must come from a fixed set, the `requirement` lists that set.

`mode` is exactly that case and the set is not listed. `key_path` is `null` too, so the one field
that would have pointed at `initial_account.mode` is empty.

## How it was resolved, and why that is not a defence

`AccountMode.__members__` -> `{'LONG_ONLY', 'SIGNED'}`. The reporter only had that on hand because
they had already dumped `dir(vqapr.public)` while chasing 020 and 021 — *"It would have been much
longer if I had not"*. Nothing in the surface states that `mode:` parses into `AccountMode`.

## What closes it

- The template says `LONG_ONLY or SIGNED`.
- `requirement: "one of LONG_ONLY, SIGNED"`, and `key_path: "initial_account.mode"`.
- No raw `KeyError` repr in `observed` for a value that failed a closed-set lookup.

If only one is done, do the template: fixing it removes the need for the message. But the message
defect is real on its own — any other mistyped enum value in a spec produces the same shapeless
refusal, and this journey happened to hit the one the package itself suggested.

## Related

`docs/issues/011.7` was `KeyError: 'component'` surfacing as a refusal, closed 2026-08-29. This is
the same class at a different key, which suggests the fix there was applied at the site rather than
to the pattern.
