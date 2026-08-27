# A registration remembers the span it already read

## Why this exists

Registration reads a dataset end to end to prove its logical key is unique and null-free. At that
moment the first and last `available_at` are sitting in front of it. Then it threw them away, and
every later caller that needed to know when a dataset begins or ends had to read the whole file
again — or, more often, guess from a calendar the data may not match.

## What changed

`DatasetRegistration` carries a `span`, and `validate` returns the registration with it attached:

```python
span, measured = check_span(registration, spec)
...
return span, timing, registration.with_span(*measured)
```

The span is a **measurement, not a declaration**. `DatasetRegistration.of()` does not accept one.
If an author could write it, it would become a second fact free to disagree with what the file
actually holds — precisely the class of defect this package refuses elsewhere.

`Workspace.span` then answers from the stored declaration without opening anything.

## The defect this had to avoid

The workspace decoder enforces **exact key-set equality**, and that check is all-or-nothing across
the whole document. Both `Workspace.open` and `create` read before they write. So adding `span` to
the encoder naively makes every pre-existing registration undecodable, and one stale entry makes
the **entire workspace** unreadable — including to `register` itself.

The first attempt refused at decode with a message naming `vqapr register <declaration.yaml>` as the
repair. That refusal is self-blocking: `list` cannot enumerate what needs fixing because it must
open, and the advertised command cannot run because it must open too. Verified directly — both
paths raised. A refusal that names a repair it has itself disabled sends the reader in a circle,
which is worse than a generic error.

So a legacy registration is **quarantined**, not rejected. It decodes as a registration whose span
is `None`; the refusal moves to the point of use:

- `Workspace.open` succeeds, so the workspace is repairable.
- `datasets` enumerates everything, so `list` can report what is stale.
- `dataset()` and `span()` refuse a quarantined entry, naming the exact repair command.
- `_encoded_dataset` writes a quarantined entry back **in its original legacy shape**, because
  `register_dataset` rewrites the whole document — inventing a span for the others would either
  fabricate a measurement nobody took or block the repair of the one dataset actually fixed.

The conflict check needed one adjustment: a repaired registration differs from its quarantined
self in exactly one way, so comparing whole registrations read that as a changed declaration and
refused the repair. It now compares the declared half and lets the measurement be what changes —
adding a span is a repair, changing anything else is a new dataset.

## Trade-off

**The span is not free, and the docstrings say so.** `span_check` is a second aggregate over the
source, not a rider on the key scan. Measured on the 7.5M-row testbed source: 0.055s against the
key check's 0.209s, about a quarter more registration time. What that buys is that every later
read costs nothing. The first draft of this record claimed the measurement was free; it was
measured and the claim was wrong, so it was corrected rather than softened.

`span.not_tz_aware` was drafted as a refusal and removed. Stage 1 already refuses a
non-`TIMESTAMP_TZ` `available_at`, and min/max cannot change a column's type, so the code was
unreachable by construction — a branch no fixture could ever produce. `with_span` still enforces
the invariant for a caller bypassing validation, and the check inside `check_span` is now an
assertion that says why it cannot fire.

## Validation

```
uv run --no-sync pytest -q                                   # 1,076 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

The real testbed workspace was re-registered end to end. The quarantine refusal fired on the
pre-existing document and named `annual_characteristics` plus its repair command; re-registering
the four declared datasets took 0.879s in total, and the three derived datasets were rebuilt by
materialization. All seven now carry measured spans.

Count gate MATCH after that full rebuild: callback_days 2096, formations 97, membership_rows
110919. Value gate exact, with weight digests byte-identical to the pre-change capture, so the
step is parity-inert as predicted.

A latent bug surfaced only because a test demanded the exact refusal code: the legacy branch
originally called `_workspace_error` without its required `stage` argument, so it raised
`TypeError` and was swallowed into a generic `workspace.open.invalid`, leaving the actionable
refusal unreachable. A second one surfaced the same way — aliasing `SPAN_STAGE` to another
module's constant is opaque to the refusal-code inventory's constant folding, and six workspace
codes silently dropped out of it.
