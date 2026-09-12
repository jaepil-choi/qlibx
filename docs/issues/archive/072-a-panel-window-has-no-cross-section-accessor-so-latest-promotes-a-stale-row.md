# 072 -- a panel window has no cross-section accessor, so `latest()` silently promotes a stale row to the current one

**Status:** **CLOSED 2026-09-04** on `step-01-072-current`, record `docs/implementations/151-a-window-has-a-cross-section.md`: `PanelWindow.current()` is the cross-section at the window's last instant (a name with no row there is absent); `latest()` keeps its meaning and its docstring says so; the skill, the three `read()` docstrings and the scaffolds name both. **Status when filed:** open. Found 2026-09-03 by the scenario testbed run 3
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-020**, with **F-019** as the second half of
the evidence), against `vqapr-0.3.0`. Confirmed against source 2026-09-04; unchanged at `v0.4.0`.
Filed although the agent marked both findings `No`: two `No` entries landing on the same accessor
is the "surface invites the mistake" shape the testbed exists to catch.

**Touches:** `src/vqapr/data/panel.py:218-226` (`PanelWindow.latest`), `:228-235` (`counts`),
`:237-239` (`max_available_at`), and the `values` mapping -- the four accessors a strategy has for
a window, none of which answers "this name's value at the evaluation instant, or nothing".

## What happens

`latest()` returns the newest non-null value **per name, anywhere inside the window**:

```python
def latest(self) -> Mapping[str, object]:
    """The newest non-null value per name inside the window; a name with none is absent."""
    for name in keys:
        present = pc.drop_null(self._column(name))
        if len(present):
            found[name] = present[len(present) - 1].as_py()
```

The docstring is accurate. It is also the only accessor shaped like a cross-section, so on a
sparse panel it is the one an author reaches for when they mean "today's row".

The run's residual-legs table has a row for a name only on sessions where that name is eligible.
Reading it with `latest()` turned *"no row today"* into *"trade it with the beta from the last
session it had one"* for about 1% of name-days -- concentrated on the first session of each month,
where the monthly universe mask turns over. Those names were traded on days they were ineligible,
with loadings up to a week stale. The headline series booked `0` for them while the package's own
accounting booked their real return, a gap of up to `3.4e-3` a day.

Nothing reports this. The returned mapping carries values, not the instants they came from, so a
name whose value is a week old is indistinguishable from one whose value is today's.
`max_available_at` gives the window's last instant but says nothing per name, and `counts()` gives
a total per name over the whole window, not presence at the end of it.

The second half of the evidence (F-019) is the same shape one step earlier: the author
materialised `beta_t` alongside `epsilon_t` in one row, then at the decision on `t-1` reached for
the only loadings the row in hand offered, `beta_{t-1}`. The "materialize once, read the panel
later" pattern makes the stale value the convenient one. That slip was the author's -- the package
did not choose it -- but it is worth recording next to this one, because **neither is visible from
inside vqapr**: every value involved was legitimately available at the decision instant, so no
point-in-time check can fire. Both were caught only because an external specification demanded a
weights-times-returns series be reconciled against the package's own accounting.

## Why

The window's accessors were built for time-series reads -- give me this name's history, give me
how much of it is there. A strategy that wants a cross-section at the evaluation instant is doing
something else, and the surface has no verb for it. `latest()` is close enough in name to be
taken for one.

## What to do

- Add the missing verb. `current()` -- the value at `max_available_at` only, a name absent when it
  has no row there -- is the accessor the sparse-panel case actually needs, and it makes the
  ineligible-name bug impossible to write.
- Failing that, make `latest()` carry its instant: `Mapping[str, tuple[object, datetime]]`, or a
  parallel `latest_at()`. An author who can see the instant can compare it themselves.
- At minimum, one sentence in the `latest()` docstring: on a sparse panel this is not the
  cross-section at the evaluation instant, and a name whose newest value is old returns it
  without a word.
- Consider whether the access record should say it. A read that returned a value older than the
  window's last instant for some names is exactly the sort of thing the record exists to make
  visible after the fact.
