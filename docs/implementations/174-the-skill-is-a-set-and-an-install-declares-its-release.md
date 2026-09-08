# 174 — The skill is a set, and an installed copy declares which release it came from

**Closes:** PRD §11.2 (skill set, byte-identical targets), §11.3 (`UC-ONBOARD-002`). **Branch:**
`develop`, on top of record `173`. **Owner decisions, 2026-09-08:** split the one skill into nine;
write byte-identical copies to both targets instead of a pointer; key the release history by path
rather than by release; `install --force` for edited files only; warn on stderr rather than adding
an envelope key. This record is the mechanism (1/2); the release-history generator and its gate
follow (2/2).

## Why

`src/vqapr/agent/skill/SKILL.md` had reached 1,011 lines and 67KB, and its `description` was
`Quantitative strategy backtesting framework — registration, materialization, simulation, and
measurement`. Both are the same defect.

Only `name` and `description` are preloaded; the body is read after a skill is judged relevant. So
a description that does not say **when** to reach for the skill is the difference between being
found and not existing. One skill spanning registration through reporting cannot have such a
description — "register my data" and "plot this backtest" are different requests, and one sentence
cannot represent both. And when it is found, the whole 67KB enters context: someone running a
backtest also loads 217 lines of status-code recovery.

The second defect was in the installer. `skill list` compared the installed bytes against the
shipped bytes and reported one boolean:

```python
current = installed_path.is_file() and installed_path.read_bytes() == shipped
```

`current: false` meant three different situations — the package moved on, the user edited the
copy, or both — and the message said, in all three, *"run `vqapr skill install` to update it"*.
Following it in the second case destroyed the user's work, because `install` overwrote
unconditionally. The material to tell them apart was already on disk (the manifest recorded the
install-time hash) and simply never consulted: `_list` read the shipped bytes, `_remove` read the
manifest, and neither read both.

## What was built

**`src/vqapr/agent/skillset.py`** — new. Owns the judgment, so it is not something only the CLI's
own verb can ask (record `168`).

- `shipped_skills()` — each directory under `agent/skills/` is one skill; returns
  `{name: {relative posix path: bytes}}`. Read through `importlib.resources`, not by walking
  `__file__`, because the path form raises under a zipimport or non-extracted install and would
  turn a verdict into a traceback.
- `released_hashes()` — `_shipped.json`: `{"<skill>/<path>": {sha256: release}}`. Absent means an
  empty table, which is the correct answer before anything has been released: we have not shipped
  those bytes.
- `judge(name, installed, *, shipped, released)` — pure, bytes in and a verdict out. Five states:
  `current`, `outdated`, `modified`, `absent`, `unknown`.
- `WRITABLE_WITHOUT_FORCE` — `{current, outdated, absent}`. The whole gate is which state is
  missing from that set.
- `upgrade_note(root)` — the cheap check every command runs: one manifest read and a string
  compare, no hashing.

**Why content rather than the manifest answers.** A skill directory can be hand-copied or cloned
and arrive with no manifest at all; a manifest can be deleted. Content always arrives. So the
package carries the hash of every file content it has ever released and the verdict looks only at
bytes. The manifest was left holding a different fact — which skills this project asked for — and
its `sha256` field was removed, because two records of one fact drift and this file's own comment
already said so.

**Keyed by path, not by release.** `{"register-dataset/SKILL.md": {hash: "0.6.0", hash: "0.7.2"}}`.
Keying by release stores a full copy of every skill on every release even when nothing in it
changed; keying by path adds an entry only when a file's content actually changes. Putting the
release in the *value* buys provenance ("your copy is the 0.6.0 one") at no extra entries. The key
is the path *inside* the skill, which is what lets one entry serve both targets.

**`src/vqapr/cli/skill.py`** — rewritten as a thin verb layer.

- Both targets receive real bytes. The file previously argued for a pointer — *"복사본이 두 개가
  되는 순간 하나는 반드시 stale해진다"* — which was true while drift was undetectable. Per-target,
  per-file verdicts remove that reason, and a pointer costs the reader an extra hop, which is the
  same problem PRD §11.2 forbids for nested references. The docstring was rewritten to say this
  rather than left contradicting the code.
- `install` writes `outdated` and `absent` files silently, refuses `modified` ones and names them,
  and never touches `unknown` paths. `--force` unlocks exactly the refused set.
- `remove` deletes what it judges ours, keeps `modified` files without `--force`, and reports
  `unknown` paths as preserved rather than deleting them.
- Directory names are `vqapr-<skill-name>` under both `.agents/skills/` and `.claude/skills/`. The
  prefix exists because that root is shared with other tools' skills, and `register-dataset` is a
  name someone else could plausibly use.

**`src/vqapr/cli/envelope.py`** — `note()`, beside `emit()`. Writes one advisory line to stderr as
UTF-8 bytes. stdout keeps carrying exactly one JSON document; an agent having a single parsing
path is that envelope's reason to exist, and it is not worth breaking for a warning. Bytes rather
than `print`, for the same reason `emit` writes bytes: cp949 on a Korean Windows console cannot
encode a path that runs through a non-ASCII profile name, and an advisory that raises would take
the command down with it. That failure was observed in test, not reasoned about.

**`src/vqapr/cli/main.py`** — every command except `skill` itself emits the upgrade note. Not
`skill list` alone: a stale skill does its damage while an agent reads it and runs something else.

## What did not change

The nine skills do not exist yet. This record moved the existing 1,011-line body wholesale into
`agent/skills/introduce-vqapr/SKILL.md` and built the machinery around a set of one. Splitting the
content is the following milestones' work, and doing it here would have mixed a mechanism whose
correctness is testable with prose whose correctness is a judgment.

`_shipped.json` is not written yet, so every table lookup misses and any copy that differs from
what is shipped reads as `modified`. That is the correct answer today — nothing has been released
from this tree — and it means the `outdated` path is exercised only by the unit tests, which
supply their own table.

## Trade-offs

**A developer rebuilding between two unreleased builds sees `modified`.** Their old copy came from
a build that was never released, so it is in no table. `--force` is the answer and the message
names it. Making local builds write to the table would mean any working tree could vouch for its
own bytes, which is the one thing the table must not allow.

**Both targets are now real bytes, so a user can edit one and not the other.** That is reported
rather than prevented: `skill list` verdicts are per target.

**The verdict is content-only, so "the user edited this" and "the download was truncated" look the
same.** Both need `--force` and a human glance, and the message we can honestly write — *this file
differs from every release vqapr has shipped* — is true of both.

## Validation

- `uv run pytest tests/ -q` — 1,481 passed, 24 deselected.
- `uv run ruff check src/` — clean.
- `tests/agent/test_an_installed_skill_declares_where_it_came_from.py` — new, 10 tests. The five
  states, the `outdated`/`modified` split with a synthetic release table, `WRITABLE_WITHOUT_FORCE`,
  the worst-file rollup, and that a hash known for one skill does not vouch for another skill's
  identical file.
- `tests/cli/test_the_stale_skill_message_names_a_real_command.py` — rewritten. `docs/issues/025`'s
  mechanical condition is kept: every `vqapr ...` in backticks anywhere in a payload is extracted
  and executed. Its `test_install_gained_no_no_op_force_flag` was **retired with its reasoning**,
  not deleted — a `--force` on the old `install` would have been a no-op, and on this one it is
  the only way past the gate.
- `tests/skill_prose.py` — new helper. Six test files each found the skill their own way and each
  broke separately; they now read the prose as a whole, so a claim that moves from `SKILL.md` into
  a `references/` file is still found.
- `tests/cli/test_agent_surface.py::test_both_targets_receive_identical_bytes` — new, pins §11.2.

`tests/characterization/test_status_sections.py` still requires a `### Recovering from: NNN`
section for every `Status` member. PRD §11.2 now says failure recovery is not a skill and those
217 lines are to be deleted, so that test will fail when they go. It is left standing on purpose:
it makes the deletion a decision someone has to take deliberately rather than a diff that slips
through.
