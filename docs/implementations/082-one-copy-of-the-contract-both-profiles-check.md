# 082 — One copy of the contract both profiles check

Issue `002`'s first half, measured and still true ten days after it was filed: the two execution
profiles carried the same contract check twice.

| part | academic | krx | identical |
|---|---|---|---|
| snapshot validation | `_validate_snapshot` | `_rows` | 20 lines, byte for byte under two names |
| `execute` preamble | 11 lines | 11 lines | byte for byte |

Two copies of one check drift the first time only one is edited. Nothing had drifted yet, which is
the only reason this was still cheap.

## Functions, not a base class

Both now live in `execution_table.py`, next to the type they check:

- `requested_rows(snapshot, requests)` — the snapshot's own contract: no duplicate requested
  instrument, boolean tradability, a positive finite price when tradable.
- `accepted_requests(orders, account, snapshot)` — types, the account-version match, one request
  per instrument, returned sorted by instrument id.

`accepted_requests` returns the sorted requests rather than validating in place, because sorting
was the last shared step and every caller needs its result. Returning it is what stops the sort
itself from becoming the twelfth duplicated line.

**A base class was the wrong shape and the issue said so.** What these check is a property of
`ExactExecutionSnapshot` and of the call, not venue policy. The profiles genuinely differ on
quantity, cost, shorting and account access, and a base class invites those to be shared. There is
also a structural reason: `load_exchange` refuses a subclass whose `execute` is not its profile's,
which is what lets a costed subclass add a band without asserting a realism it has not shown. A
shared `execute` would blur which profile's semantics a subclass claims.

So `execute` stays on each profile. Only the two preludes moved.

Verified after: the strings `must be an OrderBatch`, `duplicate requested instruments` and
`account_version does not match` each appear **zero** times in both profile files.

## The five invariants, pinned once against both

`tests/exchange/test_profile_invariants.py` runs issue `002`'s list against both profiles,
parametrised, so a profile that stops holding one fails by name:

1. one fill per request, in instrument order — the batch is fed reversed, so a profile preserving
   input order fails
2. absent row → `ABSENT`, `is_tradable=false` → `NONTRADABLE`, `delta == 0` → `NO_TRADE`
3. `is_tradable` with a zero or negative price fails the batch
4. a batch planned against another account version is refused
5. `dealt` shares its request's sign, and `|dealt| <= |requested|`

## Point 5 is written as the inequality it is

`Fill.__post_init__` already refuses a dealt quantity that exceeds its request or flips its sign,
so the contract admits a partial fill today. No profile produces one. Asserting `<=` rather than
`==` is what lets a venue profile produce one later without this file being rewritten to permit it.

The test also asserts the equality **separately**, so the day a partial fill arrives is visible
here rather than silently absorbed by the `<=`.

**A partial fill cannot arise on the academic profile at all**, and that is structural rather than
a policy choice. Academic listings are fractional, so a plan sizes exactly to the cash it has and
leaves no rounding residual. Cash exhaustion mid-batch is a whole-share artifact: it needs
rounding to whole units and charged costs to disagree with the plan's arithmetic, and the academic
profile has neither. Issue `002` recommended sequencing "on the venue profile only" as a design
preference; it is narrower than that — there is no cause to model on the other side.

## Validation

```
uv run pytest tests/ -q      # 1329 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

The refusal-code baseline was regenerated for line movement only — no code added or removed, which
is the check that the lift changed placement and not behaviour.
