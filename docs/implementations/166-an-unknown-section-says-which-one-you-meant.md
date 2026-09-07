# 166 — an unknown section says which one you meant

**Closes:** nothing tracked; found by reading the 0.6.0 spine stepper at
`declarations.py:_apply`. **Branch:** `develop @ 7d2ab0ee` (after the 0.6.0 stamps).
**Campaign:** none. **Scope:** `src/vqapr/declarations.py`. The refusal code
`declaration.read.unknown_section` is unchanged; its body, its `fix` and its `source` are not.

## Why this exists

Every level of a declaration BELOW the top goes through a pydantic model with
`extra="forbid"`, and `refusals_from` turns each `extra_forbidden` into a refusal whose `fix`
names the nearest permitted key (`_nearest_hint`). The top level — the five sections themselves —
was the one layer with no model and no hint: a hand-written `set(document) - set(SECTIONS)`
whose `fix` only read the unknown names back to the author.

Measured against `SECTIONS`, four of the five obvious singular/plural slips were near misses
`get_close_matches` resolves, and none of them were being answered:

| written | resolvable to | said before | says now |
| --- | --- | --- | --- |
| `dataset` | `datasets` | "remove or rename ... : dataset" | "rename dataset to `'datasets'`" |
| `run` | `runs` | (same) | "rename run to `'runs'`" |
| `component` | `components` | (same) | "rename component to `'components'`" |
| `execution_input` | `execution_inputs` | (same) | "rename execution_input to `'execution_inputs'`" |
| `sources` | nothing | the inline-dataset note | the note, plus a fix that says where to move it |

`dataset` is not a hypothetical: it is the exact document
`tests/cli/test_register.py::test_an_unknown_section_is_named_rather_than_ignored` writes. The
package's own test named the typo and the refusal never said the word `datasets`.

Two further defects were visible once the block was open. The refusal carried no `source`, so
the ONE refusal in `register` that could not say where in the file it pointed was the one about
the file's own top level. And every unknown section was lumped into a single `Failure`, so a
document with two bad sections got one `fix` that could not be about both.

## What was NOT done, and why

The obvious move is a top-level `Declaration` model with `extra="forbid"`, deleting the block
and inheriting `refusals_from`. It was measured and rejected:

- It renames the refusal to `declaration.read.key_unknown`. That code is asserted by
  `tests/characterization/refusal_codes.py`, `tests/cli/test_register.py`,
  `tests/cli/test_every_new_kind_says_how_to_use_its_file.py` and
  `tests/test_two_sections_carry_no_information.py`, and named by four documents. It is a
  published part of the agent-facing vocabulary.
- The model is about ten lines and the `sources` note needs a new home of about six, against a
  twenty-two-line block. The net is roughly six lines, not the reduction that would justify
  moving a published code.
- The model would unify nothing else. `SECTIONS` is a name list; the five `section(...)` call
  sites each carry different logic and stay either way.

`unknown_section` and `key_unknown` also say different things — a section the document does not
have versus a key a body does not have — and collapsing them loses that.

## What changed

- **`_SECTION_NOTES`** (module level, beside `SECTIONS`): a note and a fix for a section name
  spelling cannot reach. One entry, `sources`, which is not a misspelling of anything — it is a
  section an author is right to look for and that this package deliberately does not have, so
  the answer has to be written out. Its docstring states the rule that keeps the table from
  growing: anything `_nearest_hint` can reach stays out.
- **`_nearest_hint(..., removable=False)`**: when there is no near match, `removable` offers
  deletion as one of the answers. It is true for a key the author invented (an unknown section,
  an unknown field) and false for a value in a closed set, where the field is required and
  deleting the value leaves the declaration incomplete. Only the caller knows which it holds.
  The no-match branch drops `at {key_path}` when the path IS the written name, so a top-level
  section does not read "remove `'agendas'` at agendas".
- **`_apply`**: one `Failure` per unknown section, each with `source=_at(section_name)` and each
  with its own `fix` — `_SECTION_NOTES` when present, else the nearest-name hint. All of them
  still travel in one `Diagnosis`, so a document with three bad sections is answered once.
- **`refusals_from`**, `extra_forbidden` branch: passes `removable=True`. An unknown key one
  level down is equally removable, and that branch already fell back to `remove {key} from
  {parent}` when the permitted set was empty.

## Trade-offs

`removable` is a fourth parameter on a helper that had three. The alternative — a second
function, or post-editing the returned sentence at the call site — splits one piece of wording
across two places. The parameter is documented as the caller's knowledge, which is what it is.

`_SECTION_NOTES` is a hand-maintained table, and a stale entry would be worse than none. Its
one entry restates a rule the `_DATASET_KEYS` docstring already carries (there is no top-level
`sources:`); the duplication is the price of answering at the point of refusal.

## Validation

- `uv run ruff check src/` — passed. (`ruff format` reports this file as unformatted both
  before and after the change; the manifest's `lint` command is `ruff check`.)
- `uv run pytest tests/ -q` — 1419 passed, 23 deselected, 912 s.
- The four files that assert on `unknown_section` pass unchanged, including the `sources` case
  (`tests/cli/test_agent_surface.py::test_unknown_section_sources_explains_inline_declaration`)
  and the four retired sections
  (`tests/test_two_sections_carry_no_information.py`, which requires the word "remove" in the
  `fix` — the reason `removable` exists rather than a blanket `_nearest_hint` call).
- `test_all` was not run: this touches no run assembly, no record shape and no emitted
  scaffold, which are the three cases AGENTS.md names as unverified without it.
