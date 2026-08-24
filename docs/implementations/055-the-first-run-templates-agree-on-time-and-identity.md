# 055 -- The first-run templates agree on time and identity

A fresh Agent F completed a six-occurrence run, but logged nine friction entries. Two were blocked.
The worst blocker was the required Exchange path; that belongs to the Python public-interface
rebuild already being planned and is deliberately not encoded here. This record closes the five
CLI-contract failures that are independent of that rebuild.

Source: `kaist-thesis/vqapr-testbed/FRICTION-F.md`.

## A run template promised dates the runner rejected

The generated run spec said `start` and `end` accepted an ISO date or datetime and emitted bare
dates. `_timestamp` parsed those dates into naive midnight datetimes. `RunDefinition` then raised
`ValueError: start must be timezone-aware`, which reached the CLI as `stage: unhandled` with no
structured remedy.

The template now emits timezone-aware instants:

```yaml
start: "2024-01-02T00:00:00+09:00"
end: "2024-12-31T15:30:00+09:00"
```

The parser accepts only timezone-aware ISO datetimes. Dates, naive datetimes, malformed strings,
and non-strings now produce `cli.input.value_invalid`, naming the missing UTC offset and providing
a valid example. It does not infer a timezone from an agenda: strategy and valuation agendas could
disagree, and choosing one silently would turn an invalid boundary into a plausible wrong instant.

## Strategy-config listing hid the identity registration used

`register` reports and keys a strategy config by strategy component id. `list strategy-configs`
serialized only the nested config's `agenda_id`, because `_summarize` looked for a direct
`component_id` attribute while `StrategyConfig` owns a `ComponentRef`. Consequently
`--id f_krx_strategy` returned zero rows for a config that registration had just named that way.

The list serializer now projects `item.component.component_id` as `component_id`. The existing
substring filter therefore operates on the same identity registration exposes, while retaining the
agenda id needed by a run spec.

## Independently generated defaults could never fill

`new agendas` generated the strategy callback at 15:30. `new execution-input` generated a same-day
fill at 15:30. Execution targets are strictly later than their decisions, so every generated
strategy occurrence was impossible even though each timestamp was visibly inside the run horizon.

The generated strategy and valuation occurrences are now 15:29 and the execution target remains
15:30. The execution template says `STRICTLY LATER`, and the preflight refusal now says the same
rather than only "inside the run horizon." The run-spec end includes 15:30 so the final generated
callback's later target is inside the example horizon.

These are example defaults, not a claim that every venue closes at those times. A KRX user handling
pre-2016 data still changes both times to the historically correct pair. The invariant the files
now teach is the reusable one: decision time < execution time.

## The first command depended on an activated environment

Installing a console script into `.venv` does not place it on the global shell PATH. The installed
skill now opens with two explicit launch forms:

- activated environment: `vqapr --help`
- uv project: `uv run vqapr --help`

A missing bare command with a working uv command is described as an inactive environment, not a
missing package.

## Immutable registration had no setup correction path

The templates now state that registrations are immutable. The skill separates two remedies:

- if any run/result matters, mint a new id and update dependent configs/specs;
- in a disposable first-run workspace, retain authored files, obtain approval for the destructive
  reset, remove only project-local `.vqapr/` state, and re-register from source declarations.

No automatic unregister/replace verb is added. Mutating an identity that may already anchor a run
would erase provenance, and determining whether a result "matters" is not something the CLI can
safely infer.

## Deferred by explicit scope

F-003 and F-004 request an Exchange scaffold and a clearer callable/config contract. Another agent
is planning a ground-up rebuild of the Python public path. Adding a scaffold now would canonize the
very constructor/import surface that rebuild intends to replace. No Python public interface,
Exchange constructor, public export, or transform code changed here.

## Validation

```text
uv run --no-sync pytest tests/cli/test_commands.py tests/cli/test_agent_surface.py -q
52 passed

uv run --no-sync pytest tests/flow/test_preflight.py -q
9 passed

uv run --no-sync ruff check src/ tests/
clean

uv run --no-sync pytest -q
677 passed
```

New assertions cover structured date refusal, aware generated boundaries, component-id filtering,
causal template ordering, explicit strict-later guidance, CLI launcher selection, and immutable
workspace recovery.
