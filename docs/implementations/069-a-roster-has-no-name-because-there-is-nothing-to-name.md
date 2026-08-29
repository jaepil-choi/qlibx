# 069 — A roster has no name, because there is nothing to name

The declaration invited an identity the workspace has nowhere to put.

## What it was

```yaml
instruments:
  krx:            # <- a name
    tables:
      stock: instruments_stock.parquet
```

`.vqapr/instruments.json` stores `schema`, `tables` and `digest`. **No id.** So the name above was
read, echoed back in the registration receipt as `roster_id`, and dropped. Registering a second
roster under a different name did not create a second roster — it silently replaced the first and
returned `ok` with the new name echoed, which reads like two rosters now exist.

Re-registration being ordinary is correct and deliberate: a roster grows as a matter of course, a
daily batch lists new tickers, issuers delist, a name is reclassified. What a past run treated an
instrument as is testified to by that run's own fills. But *allowing updates* and *silently
discarding a declared identifier* are different things, and only the first was intended.

## What it is

```yaml
instruments:
  tables:
    stock: instruments_stock.parquet
```

One roster, one slot, no name. Owner ruling D3.

## The old shape is refused, not ignored

```
declaration.read.value_invalid
requirement: `instruments:` declares one roster's tables directly, with no id above them
observed   : `instruments:` maps to krx rather than to `tables`
fix        : remove the id line under `instruments:` and lift `tables:` up one level; a project
             holds one roster and each registration replaces it, so it has no name
```

Accepting the old shape with the id ignored was the obvious alternative and is forbidden: the
repository does not add compatibility shims, and "accepted but ignored" is exactly the behaviour
this record exists to remove — it would keep reading a name and keep dropping it, while now also
pretending that was intended.

The refusal names what it found and what to do, so a reader does not have to diff against a
re-emitted template to see that one line must go.

## What the receipt says instead

`roster_id` is gone from the registration envelope. In its place:

```json
{"instruments": 12, "by_kind": {"stock": 10, "etf": 2}, "digest": "..."}
```

The digest is the roster's actual handle — it is what the workspace stores and what `run` will
state (T3). Reporting an id nothing kept was the defect; reporting the digest is reporting the
thing that exists.

`by_kind` stays. It is the only mechanical guard in the roster path that fires on the **success**
path, and it is what caught a partly-commented declaration registering ten of twelve names.

## Trade-offs

**This breaks every existing declaration.** That is the point — the old shape declared something
untrue — but it is a real cost, paid once, with a refusal that says exactly how to pay it. One
consumer existed in the tree, `showcases/show_005_enhanced_index/run.py`, and it is updated. The
committed showcase *outputs* under `outputs/replicate-{a,b}/instruments.yaml` are generated
artifacts of past runs and are left as they are; they are records of what was declared then.

**The emitted template lost a knob.** `vqapr new instruments --component-id krx-universe` no longer
puts that name anywhere. The flag still names the script's stem, which is what it was always doing
usefully.

## Validation

```
uv run pytest tests/ -q      # 1306 passed, 13 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15 findings, identical to 7ae3d3af; none new
```

- `tests/test_instrument_roster.py::test_registration_refuses_the_old_id_keyed_declaration` — the
  old shape is refused, and the refusal names the id it found and the edit that fixes it. This
  replaces `test_registration_refuses_a_second_roster`, whose scenario the new shape makes
  inexpressible: with no id level, two rosters cannot be written down at all.
- `tests/cli/test_new_instruments.py::test_the_emitted_declaration_names_no_roster_id` — the
  emitted declaration carries no id, `--component-id` no longer reaches it, and the template says
  *why* there is no name, so its absence reads as a decision rather than an omission to fill in.
- The rest of `tests/test_instrument_roster.py` and `tests/cli/test_new_instruments.py` moved to
  the new shape in the same change, which is what proves the shape is the one the product accepts.

The refusal-code baseline gains no code from this change: it reuses the existing
`declaration.read.value_invalid`. Its only drift against `7ae3d3af` remains the two codes record
`068` added, with nothing removed.
