# YAML config-driven data flow

## Why

The discarded implementation exposed generated JSON definitions, mappings, snapshot metadata, and
Markdown under `config/`. That made internal registration state look like the user-facing data
loader contract and did not match the requested `base.yaml` / `sources.yaml` / dataset-fragment
workflow.

## Outcome

The replacement was built from the clean Git skeleton. Project data now follows one path:

```text
config/qlibx/data/registrations.yaml
  -> data/qlibx/*.parquet
  -> config/qlibx/data/sources.yaml
  -> config/qlibx/data/datasets/*.yaml
  -> ConfigDrivenDataLoader.load_table/load_matrix
```

`config/` contains only human-authored YAML. Generated hashes, coverage, and provenance are written
under `.qlibx/registrations/`. Upstream data remains read-only.

Registration owns only `available_at` and `ticker`. YAML `information` mappings are copied as
opaque values. No financial field names, adjustment rules, fallback mappings, or normalization are
built into qlibx. Missing mappings and ambiguity use structured errors suitable for an agent to
explain to the user.

The logical loader follows the comparative `references/configs/` pattern: `base.yaml` chooses a
physical source fragment and logical dataset fragments; DuckDB registers only declared Parquet
sources; each logical dataset declares SQL and either table or matrix output. Bounded date/ticker
filters are parameterized and matrix duplicate keys fail explicitly.

## Dependencies

- `pyqlib==0.9.7` is mandatory.
- `pandas>=2.2,<3` is direct because table/matrix results are public pandas objects.
- `pyyaml>=6,<7` is direct because YAML is the public config format.
- `duckdb>=1.3,<2` and `pyarrow>=20,<24` implement query and registration adapters.

## Trade-offs

Canonical output uses stable generated filenames so `sources.yaml` stays readable. Re-registration
atomically replaces derived output after source-stability validation; provenance records exact
source/output hashes. More complex publication calendars must be produced outside qlibx because
the built-in availability derivation is intentionally limited to an explicit calendar-day offset.

## Validation

- Temporary-contract tests cover strict duplicate-key YAML, missing mappings, duplicate dataset
  declarations, generic requirements, registration, bounded table loading, and matrix loading.
- Real registrations preserve every selected information value exactly for 8,651,872 market rows,
  449,429 membership rows, and 1,143,059 sector rows.
- Real availability validation has zero mismatches for market `-1 day`, membership `-1 day`, and
  sector `0 day`.
- The real YAML loader returned a 7-date by 2-ticker matrix with 14 non-null values.
- A fresh bounded signed long-short run loaded all eight matrices through public qlibx YAML and
  executed through Qlib 0.9.7 for 58 dates and 3,774 complete input-axis tickers. It produced 540
  negative alpha cells, 949 actual underlying sell orders and fills, 542 signed-short rows, zero
  negative composite quantity, and active PnL of 732,258,791.25 on a one-billion active book.
  Evidence: `experiments/exp_003_event_time_qlib_pnl`.

- `uv run pytest -q`: 77 passed.
- `uv run ruff check .`: passed after import-order correction.
- `uv lock --check`: resolved 218 packages without lock drift.
- Direct tree: DuckDB 1.5.5, pandas 2.3.3, PyArrow 23.0.1, pyqlib 0.9.7,
  PyYAML 6.0.3.
- `uv build`: wheel and sdist built successfully.

The previous availability-indexed experiment and its incorrect PnL claim were removed. That daily
scenario explicitly retains a separate observation date, but the package contract requires only
`available_at`; other event/observation dates remain optional user-mapped information.
