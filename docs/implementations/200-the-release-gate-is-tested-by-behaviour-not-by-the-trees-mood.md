# 200 — The release gate is tested by its behaviour, not by the tree's mood

**Date:** 2026-09-09. **Branch:** `develop`. **Reported by:** two failing tests in
`tests/agent/test_the_release_records_what_it_ships.py`, which had gone red without anyone
changing them.

## Why

`test_the_check_fails_while_content_is_unrecorded` and `test_every_shipped_file_is_named_by_the_check`
each asserted that `scripts/record_shipped_skills.py --check` **fails** — `returncode == 1` — and
names unrecorded skill files. They asserted a permanent red.

That premise was stated outright in the module docstring:

> The table is deliberately **not** in the working tree. […] So `--check` fails here, on purpose,
> and the release step is what makes it pass.

Both halves of that were wrong.

**The table is in the working tree, and has to be.** PRD §11.3 has the package *carry* the hashes
of everything it has ever shipped — *package는 자신이 정식 릴리스에서 출하한 적 있는 모든 파일
내용의 해시를 들고 다닌다* — and `skillset.released_hashes()` reads `_shipped.json` out of the
installed package via `importlib.resources`. A table absent from the tree ships empty, and an empty
table makes every install holding anything but today's bytes read `modified`. That is exactly the
false accusation §11.3 exists to prevent. `_shipped.json` has in fact been committed since
`6ac20ada`, and `bf26079f` updated it.

**The red was transient, not permanent.** The gate is red between a skill edit and the release
commit that records it, and green immediately after. When the tests were written the tree sat in
the first state; `bf26079f` ("Stamp 0.9.0.dev1 and record what it ships") moved it to the second by
recording four changed files, and the two assertions inverted. Nothing was broken — the release
flow did precisely what it is supposed to do, and the tests failed *because* it worked.

So the defect is in the tests. `.agent/project.yaml` scopes `release_check` as a release-only gate
and says so explicitly — *"Not part of `test`: between releases the tree ships content that has not
been handed out, and this check is meant to fail then."* These two tests pulled that gate back into
`uv run pytest tests/` and inverted its polarity, which made the ordinary suite depend on where in
the release cycle the tree happened to sit. Either polarity is wrong to pin: asserting green breaks
the moment someone edits a skill, and asserting red breaks the moment someone releases.

This was the second option on the table. The alternative — treat the policy as right and keep
unshipped content out of `_shipped.json` — was rejected because it contradicts §11.3 as above: the
table must be committed for the judgement to work at install time at all, and the release flow that
writes it (bump version, record, build) is already correct.

## What

`tests/agent/test_the_release_records_what_it_ships.py` only. No production source changed.

**A `repo_copy` fixture.** The script locates everything from its own `__file__`
(`REPO = parents[1]`, then `src/vqapr/agent/skills`, then `pyproject.toml` for the release label),
so the tests now copy the real script and the real skills tree into `tmp_path` under that layout
and drive the copy. That is what lets them move shipped content without writing into the working
tree — the concern the old docstring had, met by copying rather than by leaving the tree red.

The copy's `src/vqapr/` holds only `agent/skills/` and no `__init__.py`, so it is a namespace
portion; the installed regular package still wins the import, and `from vqapr.agent.skillset import …`
inside the script resolves normally. Verified, not assumed.

**The two rewritten tests assert behaviour.**

- `test_the_check_fails_while_content_is_unrecorded` — asserts the copy starts green (without that,
  the test proves nothing), appends bytes to a shipped `SKILL.md`, then asserts the gate returns 1
  and names the table, the offending path, and the real fixing command.
- `test_every_shipped_file_is_named_by_the_check` — deletes `_shipped.json` to stand in for the
  state before the first release, and asserts every shipped file is named, not a subset.

**`test_recording_adds_and_never_removes` was replaced, not kept.** Its body built a dict and
asserted a property of the dict it had just built; it never ran the script, and it passes unchanged
against a script sabotaged to drop history. Since the fixture made the real round trip cheap, it is
now `test_recording_clears_the_check_and_keeps_earlier_releases`: record, assert the gate goes
green, assert the new content landed under this release's label, and assert the hashes earlier
releases shipped are still there. Same property, actually tested.

**`test_the_script_runs_without_the_package_installed` still runs against the real tree** and still
accepts `returncode in (0, 1)`. That is the honest assertion about the working tree: the gate is
wired up and reaches a verdict rather than a traceback, without pinning a colour that is a fact
about the release cycle.

**`PYTHONIOENCODING=utf-8` is pinned for the child.** The recording branch prints the table's
absolute path, which is not guaranteed ASCII — on this machine the profile directory is Korean, and
the path arrived as mojibake through a pipe decoded as UTF-8. Only `--check` and `--help` were ever
run before, and the script keeps those ASCII on purpose; the round-trip test is the first to run the
recording branch, so it is the first to meet this.

## Trade-offs

The suite no longer notices if someone edits a skill and forgets to record it before releasing.
That is deliberate and it is not a loss: `release_check` is a declared command and the release
procedure's gate, which is where that catch belongs. Putting it in `pytest` was what forced the
inversion in the first place.

Copying a 55-file, 308 KB skills tree per test costs three `copytree` calls and three subprocesses;
the module runs in about 3.7 s.

## Validation

- `uv run pytest tests/agent/test_the_release_records_what_it_ships.py -q` — 6 passed.
- **Mutation-checked**, because tests that assert the wrong thing are the defect being fixed here:
  - `--check` sabotaged to always report green → both rewritten tests fail. Caught.
  - recording sabotaged to replace a path's history instead of adding to it
    (`table[key] = {digest: release}`) → the round-trip test fails. Caught. The tautology it
    replaced passes this sabotage.
  - Script restored and `git status` confirmed clean afterwards.
- `uv run ruff check tests/agent/test_the_release_records_what_it_ships.py` — clean.
- `uv run python scripts/record_shipped_skills.py --check` — still green at 0.9.0.dev1, unchanged
  by this work.
- `uv run pytest tests/ -q` — see handoff.

`uv run ruff check src/` reports 82 findings at the `develop` tip. They pre-date this change, which
touches no file under `src/`.
