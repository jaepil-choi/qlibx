# 095 — The stale-skill message names a command that runs

**Closes:** `docs/issues/025-the-stale-skill-message-names-a-flag-that-does-not-exist.md`.
**Branch:** `fix/025-stale-skill-message`.

## Why this change exists

```
$ vqapr skill list
{"current": false, "installed": true, "ok": true,
 "stale": "the installed skill differs from the one this package ships; run
           `vqapr skill install --force` to update it"}

$ vqapr skill install --force
{"error": "UsageError: unrecognized arguments: --force", "ok": false}
```

The tool told the reader to run a command, and the same tool rejected it. `install` accepts
`--target`, `--into` and `--dry-run` (`skill.py:204-213`). `--force` is real — on the sibling
`remove` verb (`skill.py:218-222`), where it means *remove even if files have been modified since
install*. A flag that exists on another verb with a different meaning is the worst version of this
mistake, because a reader who checks `--help` for `remove` finds it and concludes they misread.

Found while installing the package for the journey, **before the run started** — the first thing the
package said to this reporter was an instruction that did not work.

## What changed

One sentence. `vqapr skill list` now names `vqapr skill install`.

**No flag was added to `install`**, and that is the load-bearing half of the decision. Adding
`--force` would have made the original message correct, and it would have been a **no-op**: plain
`install` already overwrites a stale copy, and `skill list` then reports `current: true`. Verified
directly before choosing the fix — install, tamper with the installed `SKILL.md`, confirm
`current: false`, run plain `install`, confirm `current: true`.

An option that exists only to justify a message is worse than the message was: it adds a real
surface, needs its own help text and tests, and teaches a habit that does nothing.

## Validation

**Gate:** fast + `tests/cli/test_agent_surface.py` + `tests/cli/test_new_exchange.py`.

| check | result |
|---|---|
| `tests/cli/test_the_stale_skill_message_names_a_real_command.py` (new) | 3 passed |
| named gate files | green |
| full fast suite | **1383 passed, 14 deselected** |

The merge condition asked for a mechanical check, and the test is mechanical in the strong sense:
it builds a genuinely stale install, **extracts the command from the message itself** with a
backtick match, and **executes it as a subprocess**. It cannot pass by agreeing with a hard-coded
string it also asserts — if the sentence names anything that does not run, the test fails whatever
the sentence says. It then confirms `skill list` reports `current: true`, so naming a command that
runs but does not fix the staleness would also fail.

Two further tests hold the decision in place: `skill install --force` must still be **rejected**, so
a later reader cannot quietly add the no-op flag; and `skill remove --force` must still work, so the
flag was not moved off the verb it belongs to.

This campaign produces genuinely stale installs as a side effect — five branches touched `SKILL.md`
— so the fixture reproduces the reporter's exact situation rather than approximating it.
