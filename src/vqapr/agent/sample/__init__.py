"""The sample journey `vqapr new sample --out DIR` materializes (PRD §11.4, record `172`).

A strategy (`reversal_5d.py`), a venue (`exchange.py`), a synthetic panel (`data/`) and, once
materialized, the one declaration that registers them all and the run that ties them together.
`materialize.materialize(out_dir)` is what the CLI calls and what the package's own tests call, so
the door the suite exercises is the door a user opens.
"""
