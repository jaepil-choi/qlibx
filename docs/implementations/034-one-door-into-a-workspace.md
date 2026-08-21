# 034 — One door into a workspace

## Why this exists

Record 033 shipped `vqapr declare` beside `vqapr register` and, in doing so, split registration
into two verbs. The user rejected the split on the right grounds:

> register가 애초에 필요한 yaml을 같이 요구해야 하는거고 그게 없으면 아예 register를 거부해야 해.

That is what canon §10.2 already drew — `vqapr new` emits *"구현 파일 + yaml"* and the user then
types `vqapr register .`. Record 033 kept `register`'s argv shape and bolted a second command
beside it, which produced two doors into one workspace and a `new` that emitted only half of what
`register` needed.

## What changed

**`register` takes one declaration file and nothing else.**

```
vqapr register <declaration.yaml>
```

Seven sections, applied in dependency order: `datasets`, `execution_inputs`, `agendas`,
`components`, `strategy_configs`, `valuation_configs`, `monitoring_policies`. `declare` is deleted.

**`new` emits the declaration next to the component.** `vqapr new strategy my-alpha` writes
`my_alpha.py` **and** `my_alpha.yaml`, and the second is immediately registrable:

```yaml
components:
  my-alpha:
    kind: strategy
    path: my_alpha.py
    object_name: MyAlpha
```

Without this, `register`'s requirement would be unsatisfiable for a first-time user: they would
have to write that YAML from documentation on their first command, which is exactly where they are
least able to guess field names. `new` → `register` is now the whole path from nothing to a
registered component.

**A relative path resolves against the declaration's directory**, not the process working
directory, for code and data alike. One rule for every path in the file. Resolving them differently
would make a document portable only by accident, and `new` emits `path: my_alpha.py` beside
`my_alpha.py` precisely because that is the shape a user can move.

## Why a component cannot be registered from argv

`register strategy my-alpha ./alpha.py MyAlpha` looks complete and is not. It registers a component
without the dataset it reads or the cadence it runs on — a component no run can use. That is the
"registered but unusable" state the package refuses everywhere else, reached through the front
door.

The declaration is therefore the unit of registration, not the component. A file can carry a
component alone (what `new` emits), or data alone, or the whole workspace; what it cannot do is
register a component while pretending its dependencies are someone else's problem.

## The validation is real, and it already existed

The user asked for actual validation at registration — *"trade_at, ticker 이 pk여야 해"*. That check
was already built and is now reachable from the CLI. Registering a source whose
`(available_at, instrument)` repeats:

```
exit=1  stage=dataset.register.key
  [dataset.register.key.duplicate] logical key (available_at, instrument) must be unique
  examples: ["(datetime(2024,3,5,3,0,tzinfo=KST), 'A') x2"]
  workspace written? False
```

It scans the **whole** source, names the duplicated group as evidence, and writes nothing. This
matters more than it looks: a duplicated logical key silently changes what a lookback window
contains — the same instant contributes two rows, so a declared lookback of 2 may see one day of
history — and nothing downstream can detect it. The same door checks that every declared column
exists and that `available_at` is timezone-aware, which is what makes point-in-time reads
meaningful.

Components go through `conformance()` (record 032), so a component whose callback cannot receive
Flow's call is refused at the same door.

## Verified as a first-time user types it

Empty directory to a completed run, CLI only, no library import anywhere:

```
$ vqapr register workspace.yaml
  {"registered": {"datasets": ["prices"], "execution_inputs": ["venue-daily"],
                  "agendas": ["alpha", "valuing"]}}
$ vqapr new strategy my-alpha --dataset prices --lookback 2
  {"path": ".../my_alpha.py", "declaration": ".../my_alpha.yaml", "object_name": "MyAlpha"}
$ vqapr register my_alpha.yaml
  {"registered": {"components": ["my-alpha"]}}
$ vqapr register rest.yaml
  {"registered": {"components": ["venue"], "strategy_configs": ["my-alpha"],
                  "valuation_configs": ["valuing"]}}
$ vqapr run spec.yaml
  {"ok": true, "stage": "run.complete", "occurrences": 9, "account_version": 9}
```

## Trade-offs

- **`register` no longer reports a fingerprint in its reply.** It reports what was registered per
  section, because one call can register several things. `vqapr list components` shows fingerprints.
- **`new` writes two files and refuses if either exists.** Emitting one and skipping the other on a
  partial collision would leave a half-scaffolded component.
- **`new` declares only the component**, not the dataset or agenda it will need. Those are facts
  about the user's project; inventing plausible values would produce a document that registers
  something the user did not mean.
- **`sources` has no section.** A source is declared inside the dataset or execution table that
  projects it, because they register as a pair and a projection without its file is not usable.
- **`.vqapr/workspace.yaml` is still an unguarded output.** The user raised tamper-detection and
  then judged the responsibility not obviously worth it; nothing was built. It is recorded in the
  handoff as an open question rather than silently dropped.

## Validation

```
uv run pytest -q                  609 passed (from 605), run twice
uv run ruff check src/ tests/     clean
```

Eleven tests in `tests/cli/test_register.py` pin the refusals; `test_commands.py` drives the whole
path end to end. The load-bearing ones:

- `test_a_duplicated_logical_key_is_refused_with_the_offending_group` — the PK check, with evidence
  and nothing written.
- `test_a_column_that_does_not_exist_is_refused_against_the_real_file` — the declaration is checked
  against data, not accepted on trust.
- `test_a_naive_available_at_is_refused` — point-in-time reads need a zone.
- `test_a_component_declaration_resolves_its_path_beside_the_document` — what `new` emits works
  from any working directory.
- `test_a_component_that_cannot_receive_the_call_is_refused` — conformance runs at this door.

**Unrelated flake observed, not caused here.** `tests/test_workspace_concurrency.py::
test_parallel_registrations_all_survive` failed once with `workspace.open.unreadable` during a full
run, then passed 6/6 in isolation on the stashed tree and 2/2 in full runs afterwards. It touches
no CLI code. Recorded in the handoff rather than left as a silent one-off.
