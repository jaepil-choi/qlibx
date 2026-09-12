# Prove the timezone on one known instant

Naming the right zone is not enough. A schema-valid, timezone-aware column can still hold the
wrong instant, and registration cannot tell the difference — a daily row shifted by nine hours has
exactly the same schema as a correct one.

## The procedure

Before converting the whole file:

1. Pick one row whose local wall time and UTC equivalent you already know.
2. Run that row through **the exact preparation code** — not a simplified version of it.
3. Assert the local date, the local time, the UTC offset, and the UTC instant.
4. Convert it back to the venue zone and assert the original wall time is recovered.

Step 4 is the one that catches an error steps 1–3 miss, because a shift applied twice in opposite
directions still round-trips through a single conversion.

## The pyarrow footgun this exists for

```python
# WRONG: preserves the epoch value, changes only how it displays.
# This does **not** mean "read this wall clock as Seoul time".
arr.cast(pa.timestamp("us", tz="Asia/Seoul"))

# RIGHT: interprets the naive wall clock as being in that zone.
import pyarrow.compute as pc
pc.assume_timezone(arr, "Asia/Seoul")
```

A naive `2024-01-02 15:30` cast the first way becomes `2024-01-03 00:30+09:00` — a valid,
timezone-aware, look-ahead-carrying value that every check accepts.

## Why registration will not do this for you

vqapr refuses a naive timestamp rather than localizing it. Only the user knows which instant a
value means, and a wrong localization is a silent point-in-time leak rather than an error — so the
package declines to guess and says so at registration.

Localize at the instant the row became knowable. A daily close is knowable at that session's close
in the venue's timezone, which is a fact about the market, not about the file.

## A worked assertion

```python
import pyarrow as pa
import pyarrow.compute as pc

one = pa.array(["2024-01-02 15:30:00"], type=pa.timestamp("us"))
localized = pc.assume_timezone(one, "Asia/Seoul")

assert localized[0].as_py().isoformat() == "2024-01-02T15:30:00+09:00"
assert localized.cast(pa.timestamp("us", tz="UTC"))[0].as_py().hour == 6   # 06:30 UTC
assert localized.cast(pa.timestamp("us", tz="Asia/Seoul"))[0].as_py().hour == 15  # back again
```

Run this against the user's own known instant, with their own preparation code between the read
and the assertions. A test that exercises a rewritten version of the pipeline proves nothing about
the pipeline.

## Related

- [point-in-time.md](point-in-time.md) — what instant the value should carry in the first place
