# 144 — two registry sections that carried no information are gone

**Closes:** nothing in `docs/issues/` -- this was never filed as an issue. It is decision D2 of
`docs/refactoring/2026-09-03-the-deletion-campaign.md` (Step 3), made by the owner on 2026-09-03:
*"사용하지 않는 key는 반드시 없애야지. key는 사용할 때 만들어야 해. 미리 만들어두면 안돼."*
**Authority:** record `139` ("the three config sections stay … retiring the first two is a
separate decision"); architecture §17.3 (a run is configuration).

## Why this exists

A declaration document said one fact three times:

```yaml
agendas:
  daily-valuation: {role: valuation, ...}         # the agenda's own role
valuation_configs:
  daily-valuation: {agenda_id: daily-valuation}   # the key was discarded on read
runs:
  my-run: {valuation: {agenda_id: daily-valuation}}
```

The middle one decoded to `ValuationConfig(agenda_id, VALUATION)`: a role the agenda already
declared, under a key `declarations._apply` threw away. Registering a run checked the agenda's
role directly (`_require_agenda`) and did not need the section -- and then `preflight_run` looked
the section up anyway and refused a run that registration had accepted, with a message telling
the author to write the fact a third time. `monitoring_policies` was the same shape.

A registry kind costs a `_State` field, a `__slots__` entry, encode, decode, detach, merge,
lookup, `register_*` on `Workspace` and `Transaction`, a `list` kind, an `rm` kind, a template
block, a skill paragraph, a public registrar and its `__all__` entry -- for these two, all of it
for a set of agenda ids the agendas section already was.

## What changed

- **`workspace.py`, `workspace_codec.py`, `declarations.py`.** The two kinds are gone from
  `_State` (seven fields), the constructor, `_from_state`, `_state`, `_read_or_empty`, `create`,
  `_replace_state`, `_write`, `_encode`, `_decode`, `Transaction`, `remove`'s position map and
  `_references_in`. Two register stages, two `_detach_*`, two `_merge_*`, two lookups, two
  properties, two `register_*` on each of `Workspace` and `Transaction`, two `_apply` loops.
- **Reading a 0.3.0 document.** `_decode` still admits the two roots and drops them; the next
  write omits them. A section with no information is not a meaning kept in two spellings (design
  §2.4 forbids that; this is the other case). A user's **declaration** that still carries either
  is refused by `declaration.unknown_section`, naming it, as any unknown section is.
- **`flow/preflight.py`.** `valuation = definition.valuation`, `monitoring =
  definition.monitoring`; the role is checked where the agenda is frozen, as before. The
  "reference drift" refusal is gone with the second copy it compared against.
- **CLI, skill, template, public API.** `list` and `rm` lose the two kinds; `new agendas` emits
  `agendas` + `strategy_configs` and its docstring says why the third block left;
  `SKILL.md` steps 7 and the `list` paragraph; `vqapr.public.register_valuation_config` and
  `register_monitoring_policy` are deleted (breaking, by the campaign's policy). `ValuationConfig`
  and `MonitoringPolicy` stay: they are the type of a run's own `valuation:` / `monitoring:`
  binding, which is where the choice lives.
- **Sample and showcase.** `agent/sample/journey.py` and `show_001` stop registering the two.
- **Tests.** Fourteen files stop registering or listing them; `tests/test_two_sections_carry_no_
  information.py` holds the three properties: a 0.3.0 `workspace.yaml` opens and is rewritten
  without the sections, a declaration carrying one is refused by name, the registrars are not
  public names. `tests/cli/test_check.py`'s fixture no longer registers a valuation config and
  `check` passes -- the preflight refusal this record removes.

## What a user sees

| | before | after |
|---|---|---|
| declaration YAML | `agendas` + `strategy_configs` + `valuation_configs` (+ `monitoring_policies`) | `agendas` + `strategy_configs`; the run's `valuation:` block names the agenda |
| `vqapr run` on a registered run | refused at preflight without a valuation config | runs |
| `vqapr list valuation-configs` | a kind | not a kind |
| a project registered with 0.3.0 | -- | opens; the two sections disappear on the next write |

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rfE      1345 passed, 1 failed -> the refusal-code inventory,
                                                    regenerated deliberately (below); characterization 86 passed
PYTHONUTF8=1 uv run pytest tests/showcases -m ""    9 passed;  show_003 by hand: exit 0
uv build                                            dist/vqapr-0.3.0-py3-none-any.whl
uv run vulture                                      nothing new in src/
```

Branch point (`develop @ d59e0208`): fast 1322 / slow 21 deselected. This branch adds three
tests and removes none.

`src/` diff: 10 files, +33 / -306. `workspace.py` 1,801 -> 1,659; `workspace_codec.py` 1,168 ->
1,035; `declarations.py` 1,150 -> 1,130. Eight refusal codes left the inventory
(`workspace.{valuation_config,monitoring_policy}.register.{conflict,invalid,missing,reference}`),
and `tests/characterization/refusal_codes.baseline.json` was regenerated with
`python -m tests.characterization.refusal_codes` after confirming that is the whole drift.
