# `agent/sample/` — the sample journey behind `vqapr new sample`

PRD §11.4: a fresh user can **explicitly materialize** a small sample — data, project-local logic,
config, expected result — to see the whole mental model run before authoring anything. This
package is that sample, and the door is one command:

```bash
vqapr new sample --out ./first-run
vqapr register ./first-run/sample.yaml
vqapr check sample-run
vqapr run sample-run
```

## What is here

| file | role |
|---|---|
| `reversal_5d.py` | the strategy a user's copy is registered from: a five-day reversal, long-only |
| `exchange.py` | a zero-friction academic venue listing the ten sample names |
| `materialize.py` | `materialize(out_dir)`: copies the two sources and the panel, writes `sample.yaml` and a README |
| `data/` | the **synthetic** panel (`observations.parquet`, `execution.parquet`, `instruments.csv`, `panel.json`) and its provenance note |

The data is not market data: it was cut once from a private KRX warehouse by
`scripts/build_sample_panel.py` and transformed (codes and names replaced, prices rescaled and
jittered, volumes scaled) so it can be committed and shipped. `data/README.md` says exactly how.

## History

Record `170` moved the sample out of `src/` because nothing reached it: no command, public name or
skill path, only the test suite. Record `172` gave it a door and brought it back, with the panel
committed instead of built from the warehouse on every test session. The suite installs the sample
through `materialize()` and `vqapr register`, the same path a user takes (`tests/sample/journey.py`).

## Boundaries (unchanged since the PRD)

- A reference journey, not a hidden built-in alpha and not a mandatory starter layout.
- Never generated into a project the user did not ask for.
- The files it writes are product-owned examples; the user's research code is theirs.
