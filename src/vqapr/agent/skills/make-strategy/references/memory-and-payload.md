# State between decisions

## One instance, the whole run

The framework constructs the strategy once and calls `decide()` on that instance for every
session. **Never build a new instance per callback** — anything held on `self` outside
`self.memory` survives, and code written as though each callback were fresh silently loses it or,
worse, keeps it in a way the record cannot reproduce.

## `self.memory` — strict JSON

Restored before every `decide()`, snapshotted after. Read it, change it, leave it; there is
nothing to save explicitly.

**On the first callback it is `{}`** — an empty mapping, not `None` — unless the run declares an
`initial_model_memory` under its strategy entry, in which case it is that value. So the example
below runs on session one as written.

"Strict JSON" is the constraint that bites: no `Decimal`, no `datetime`, no set, no tuple key.
Store what will round-trip and rebuild the rest.

```python
def decide(self, call):
    seen = self.memory.setdefault("sessions", 0)
    self.memory["sessions"] = seen + 1
```

Outside a run — a fresh instance you construct yourself in a test — `self.memory` is `None` until
the framework restores it; `inputs()` is called on such an instance and must not read it.

## Warm-up is a `Hold`, not a failure

Two strategies with different lookbacks reach their first real decision on different sessions. The
callbacks before that are ordinary callbacks that return `vq.Hold(reason=...)`. Expressing warm-up
as an exception makes a normal condition look like a defect in the record.

## `save_payload` / `load_payload` — everything else

State that will not fit strict JSON — a fitted model, an array, an object graph — goes through
this pair.

**Preflight proves the pair before the first callback**, and the proof is stricter than it looks:

1. `save_payload` on a fresh instance
2. `load_payload` on a **second** fresh instance with those bytes
3. `save_payload` again — and the two byte strings **must match**

Two consequences follow, and they are the two mistakes:

**`save_payload` must be deterministic.** No timestamp, no `id()`, no unordered set iteration, no
dict built from a set. Anything that varies between two calls on equivalent state fails step 3,
and the failure looks like a framework problem rather than a hashing one.

**`load_payload` must accept an empty source.** The default `save_payload` writes nothing, so a
bare `pickle.load(source)` refuses the run with `EOFError` before any decision is made. Handle the
empty case first:

```python
def load_payload(self, source):
    data = source.read()
    if not data:
        return          # a fresh run has nothing to restore
    self._model = pickle.loads(data)
```

The refusal names **which of the three steps** failed and carries the original exception, so read
the step before rewriting the method.

## What memory must not carry

Not the account, not the clock, not what the run declared. Those are the framework's, and a copy
kept in memory is a second answer that can disagree with the first.
