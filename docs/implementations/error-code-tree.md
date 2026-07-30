# Error codes become a tree, named for the action they demand

## Why this change exists

The code scheme was organized by **which module noticed the failure** — `QLIBX_STRATEGY_*`,
`QLIBX_EXECUTION_*`, `QLIBX_RESEARCH_*`, and thirty-odd more prefixes. That guarantees
duplication: any failure two modules can hit earns a new name in each. It had:

| One failure | Codes for it |
|---|---|
| a named thing is not registered | 14 |
| a path escaped its configured root | 8 |
| stored bytes fail their digest | 6 |
| `schema_version` unsupported | 5 |
| a source file is not there | 4 |
| a limit must be positive | 4 |
| an immutable identity collided | 3 |
| **availability was never declared** | **2** |

The last one is the clean example. `QLIBX_DECISION_AVAILABILITY_UNDETERMINED` and
`QLIBX_EXECUTION_DATASET_AVAILABILITY_MISSING` are the same refusal — qlibx will not guess
when an observation became visible — split only by which surface reached it first.

## What changed

**Level 1 is now what the caller must do next**, which is the axis `action` and `recovery`
already carried:

```
NOT_FOUND    a named thing is not there            -> choose from what is, or restore it
MISSING      a required declaration was never made -> declare, register, or bind it
INVALID      a supplied value breaks a rule        -> correct the value
BOUNDARY     something escaped a declared boundary -> bring it back inside
CONFLICT     collides with immutable/committed state -> do not overwrite, re-derive
CORRUPT      stored bytes fail their digest        -> do not consume, reproduce
UNSUPPORTED  this build does not implement it      -> use a supported version
```

The subject moves into `context`, where it already lived (`dataset`, `role`, `path`, `kind`).

144 codes became 126. The 18 that disappeared were exact duplicates, and the merge is
evidenced rather than asserted: after the rename, `ERROR_GUIDANCE` had twelve *literal
duplicate keys*, which Python had been silently resolving last-wins. Each merged code now
carries one deliberate recovery instead of whichever copy happened to be written last.

**The tree also became real in the guidance, not just in the names.** `FAMILY_RECOVERY`
holds one entry per family and `error_guidance()` resolves a leaf against it:

```json
{"code": "QLIBX_INVALID_PANDAS_KIND",
 "family": "INVALID",
 "family_recovery": "The value breaks a rule the contract declares. ..."}
```

A leaf carries its own `recovery` only when it has something to add. Twenty-nine leaves
previously repeated one of two generic texts — 25 of them shared *one* string, copied by a
dict comprehension. Those now inherit their family.

## Behavior change

Every error code is renamed. This is a breaking change to the public contract, taken
deliberately: the codes are the agent-facing surface, and leaving 144 names for 126 failures
in place would have made the tree cosmetic.

`error_guidance()` (and so `qlibx errors <code>`) gains `family` and `family_recovery`.
Existing consumers that read `recovery` still work, except for the 29 leaves that now answer
with `family_recovery` only.

## Two invariants added, so this cannot drift back

- `test_every_error_code_belongs_to_exactly_one_family` — a code outside the seven, or
  matching two, fails. Mutation-checked by renaming one code to `QLIBX_LEGACY_*`.
- `test_no_two_codes_give_the_same_recovery` — two codes with one recovery are one failure
  wearing two names. Mutation-checked by pointing one leaf at another's text.

The second is the one that would have caught the original drift, and it caught two live
cases during this change that the mapping had missed. It is also the rule for adding a code:
if the recovery matches an existing one, it is that code, and whatever distinguishes the
case belongs in `context`.

## Trade-offs

- **`NOT_FOUND` and `MISSING` need a stated boundary or they blur.** The rule used here:
  `NOT_FOUND` is *you named something that is not there*; `MISSING` is *you did not name
  something required*. File absence is `NOT_FOUND` even when the old name said `MISSING`.
- **`UNSUPPORTED` is narrower than the old name suggested.** It now means a version or
  format this build does not implement. Closed enums moved to `INVALID`, so
  `QLIBX_TARGET_SEMANTICS_UNSUPPORTED` became `QLIBX_INVALID_TARGET_SEMANTICS` — the old
  name implied a capability gap where the real answer is "that is not one of the choices".
- **126 is still a lot.** The estimate given before the work was ~35; that was wrong, and it
  was wrong because most recoveries are genuinely distinct. Collapsing further would delete
  information rather than duplication. The count is not the target; mutual exclusivity is.
- Codes were renamed by script with an explicit mapping, verified against the live code set
  before running: no code unmapped, no mapping entry unused.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `140 passed, 1 failed`, the two new invariants being the increase over
  the 138 baseline. The failure is the pre-existing Windows `cp949` console-codec error in
  `tests/acceptance/test_p0_p1_agent_journey.py`.
- The existing bidirectional guard (every raised code documented, every documented code
  reachable) held throughout, which is what made a 144-code rename safe to do mechanically.
- `qlibx errors` checked directly for a leaf with its own recovery, a leaf that inherits,
  and a merged code.

## Not done

Pydantic was considered and declined for now. It fits the YAML layer, where `loading.py`
hand-writes key/type/`schema_version` checks and `documentation.SCHEMAS` is a hand-kept dict
that could be generated. It does not fit the pandas-carrying runtime objects: those
validations are relationships between values and between objects (look-ahead, axis match,
universe alignment, child bounds), which a model declaration cannot express — the same code
would move into `@model_validator` unchanged, while field-level failures would start
arriving as `ValidationError` instead of `QlibxError`. Splitting the error contract in two
is exactly what this change removed.
