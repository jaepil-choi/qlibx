# 091 — The run-spec template offers account modes that exist

**Closes:** the template half of
`docs/issues/017-the-template-offers-an-account-mode-that-does-not-exist.md`. The message half —
a mistyped closed-set enum surfacing as an exception repr rather than as the permitted set — is
`fix/017-closed-set-refusal`, the next branch.
**Branch:** `fix/017-template-account-mode`.

## Why this change exists

`vqapr new run-spec` emitted:

```yaml
initial_account:
  cash: "1000000"
  mode: LONG_ONLY              # LONG_ONLY or LONG_SHORT
```

The comment reads as a closed set of exactly two. The book was long/short, so the author took the
value the template offered. **`LONG_SHORT` does not exist and never did.** `AccountMode` has
`LONG_ONLY` and `SIGNED` (`account/account.py:14-19`), and `grep -rn LONG_SHORT src/` found exactly
one occurrence: the template comment itself.

Severity `slowed` for a reporter who could go read the enum; the issue records it as `blocked` for a
first-time user without the enum already on screen. The scaffold's whole promise is that what it
emits runs as written.

## What changed

One line of `src/vqapr/cli/new.py`, and the way it is produced.

The list is now **derived from the enum** rather than restated:

```python
_ACCOUNT_MODES = " or ".join(mode.name for mode in AccountMode)
```

and `_RUN_SPEC_TEMPLATE` became an f-string that interpolates it. A hand-written list is a second
definition of a closed set, and this issue is what that costs. Adding or renaming a member now
updates the template in the same edit; it cannot drift again.

`.name` rather than `.value`, deliberately: the spec is parsed by member name (`LONG_ONLY`), while
`.value` is the lowercase `long_only` a reader must not type into the file. Offering the wrong
spelling would have swapped one unusable value for another, so a test pins it.

Making the template an f-string required escaping its one existing brace pair (`positions: {}`).
Verified by emitting the file and parsing it: `initial_account` reads back as
`{'cash': '1000000', 'mode': 'LONG_ONLY', 'positions': {}}`.

## A note for the next branch

`fix/020-krx-is-long-only` edits **this same line** to add a sentence about the venue having to
agree with the account's direction. The plan serializes them for exactly this reason. That branch
must extend this comment, not replace it, and must not reintroduce a hand-written mode list.

## Validation

**Gate:** `test_all` (the scaffold changed) + `tests/cli/test_commands.py`.

| check | result |
|---|---|
| `tests/cli/test_the_template_offers_modes_that_exist.py` (new) + `test_commands.py` | 25 passed |
| **full suite, all marks** | **1376 passed, 0 failed**, 411.95s |

The emitted file was also checked directly rather than only through the template constant: `vqapr
new run-spec` writes a file containing no `LONG_SHORT`, offering `# LONG_ONLY or SIGNED`, and still
parsing as YAML.

The four tests state the property rather than banning one spelling: every mode the comment names
must be a real `AccountMode` member, every member must be offered (a closed-set comment that omits
one is the same defect pointed the other way), the list must be the derived constant rather than a
restatement, and the spelling must be the one the parser accepts.
