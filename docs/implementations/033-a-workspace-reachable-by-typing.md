# 033 — A workspace reachable by typing

## Why this exists

`register` took all four extension points after `5449ad0`. Seven other things a run needs had **no
CLI path at all**:

```
datasets · sources · agendas · execution-inputs
strategy-configs · valuation-configs · monitoring-policies
```

`list` could read all of them. Nothing could write them. The proof was in the test suite: the
`_workspace_for_run` fixture in `tests/cli/test_commands.py` reached past the CLI into the library
for all seven, under a file docstring that admitted it —

> Datasets, sources, agendas, execution inputs and configs are registered through the library,
> because the CLI has no command that registers them. That asymmetry is a finding, recorded in the
> handoff, not a thing this file works around silently.

Since `85649a5` an execution input is **mandatory for every run**, and `register execution-input`
did not exist. So a user typing only `vqapr` commands could not reach a runnable workspace at all,
not merely an inconvenient one.

## One command taking a file, not seven taking flags

The handoff proposed splitting three trivial ones into argv (`register strategy-config <component>
<agenda>`) and giving the other four a YAML projection. This ships **one** command for all seven
instead, for two reasons.

**`register` means "fingerprint this code".** It takes a path, an object inside it, and produces a
`ComponentRef` whose identity is a hash over the source. None of the seven has source or an object.
Putting `register strategy-config alpha my-agenda` next to `register strategy ./alpha.py MyAlpha`
would give one verb two meanings, and the argument shapes would not even rhyme.

**They reference each other.** A strategy config names an agenda; an execution input carries a
source; an agenda can take its sessions from a dataset. Seven separate commands means discovering
the required ordering by failing, seven times. One document is applied in dependency order —
`_SECTIONS` is that order, and it is the reason `datasets` is applied before `agendas`.

A file is also the artefact worth keeping. A workspace becomes reproducible by re-running one
declaration, which is why `run` already takes a spec rather than twenty flags.

## What the file looks like

```yaml
datasets:
  prices:
    source_id: price-source          # the dataset and its source register together
    path: ./observation.parquet
    instrument_field: instrument
    available_at: available_at
    key_fields: [available_at, instrument]
    fields: {close: close}

agendas:
  alpha:
    role: strategy_callback
    from_dataset: prices             # the sessions the dataset actually has
    at: "04:00"
    timezone: Asia/Seoul
```

Every section is optional, so a document declaring only `agendas:` declares agendas. The file grows
with the workspace instead of demanding everything on the first command.

## Two decisions worth naming

**`from_dataset` over a hand-written session list.** A cadence usually follows the data it reads,
and `Workspace.evaluation_times(dataset_id)` already knows those days exactly. Restating them in
the file is a chance to disagree with the dataset for no benefit. `sessions:` remains for cadences
that do not follow a dataset, and declaring both is refused rather than resolved by precedence —
the command must not answer by guessing which one the user meant.

**Agendas are built through `OperationAgenda.daily()`, never assembled by hand.** `daily` derives
the occurrence id scheme, the fold, and the offset from the zone. The fixture this replaced typed
`0` and `"+09:00"` directly, which is correct until the venue observes DST, after which it is wrong
twice a year and right on every day anyone tests. The command re-implements none of it.

## The bug the first run found

`declare` opened the workspace up front, the way `run` does. That failed with
`workspace.open.missing` on a fresh project — because `declare` is the *first* command typed in an
empty directory, and the registrars create the workspace on the way in.

The workspace is now opened lazily, only when a section actually needs to read one (`agendas`
resolving `from_dataset`, `strategy_configs` resolving a component). A first declaration of
datasets alone touches no workspace read at all. Reporting `workspace.open.missing` sends a user to
fix a directory when their file was correct, which is the same class of misdirection record 029
fixed in `run`'s key checking.

## Evidence the gap is closed

The `_workspace_for_run` fixture now builds the entire workspace by calling `main(argv)`. Removing
the library imports it no longer needs deleted **18 imports** from that file — ruff found every one
of them, which is a more honest measure of the gap than any prose:

```
register_dataset · register_execution_input · register_agenda · register_component
register_strategy_config · register_valuation_config · register_monitoring_policy
DatasetRegistration · ExecutionInputRegistration · ExecutionTableSpec · FillConvention
FillSelector · SourceSpec · StrategyConfig · ValuationConfig · MonitoringPolicy
ComponentKind · component_ref
```

`test_run_executes_a_declared_spec_end_to_end` still passes, unchanged in what it asserts:
`occurrences=12, account_version=7`. The same run is now reached by typing.

## Trade-offs

- **`sources` has no section of its own.** A source is declared inside the dataset that projects
  it, because `register_dataset(registration, source)` takes them as a pair — a projection without
  its file is not usable, and a separate section would let a document declare half of one. An
  execution input carries its own source the same way.
- **`valuation_configs` and `monitoring_policies` are keyed by a name that is not stored.**
  `ValuationConfig` holds only an agenda id and a role, so the mapping key is documentation for the
  reader rather than an identity. Keying them by agenda id would read as though a second thing was
  being named.
- **No `--dry-run`.** Each registrar validates and writes on its own; a preview would need a second
  code path that could disagree with the first about what is valid.
- **The command does not delete or replace.** It declares. Removing a declaration is not yet
  reachable from the CLI, and that gap is real but separate.

## Validation

```
uv run pytest -q                  605 passed (from 599)
uv run ruff check src/ tests/     clean
```

Six new tests in `tests/cli/test_declare.py` pin how it refuses; the end-to-end proof lives in
`tests/cli/test_commands.py`, where the fixture that once documented this gap now demonstrates it
is closed. The load-bearing ones:

- `test_the_first_declaration_creates_the_workspace` — the empty-directory bug above.
- `test_an_agenda_takes_its_sessions_from_the_dataset_it_follows` — the short path works.
- `test_an_agenda_must_declare_exactly_one_source_of_sessions` — both is refused, not resolved.
- `test_an_unknown_section_is_named_rather_than_ignored` — a typo cannot report success having
  declared nothing.
