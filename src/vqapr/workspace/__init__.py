"""The workspace: what a project keeps between commands, in `.vqapr/workspace.yaml`.

`registry.py` opens it, looks things up and writes one transaction under the lock;
`declarations.py` is the shape of the document; `run_definition.py` is one declared run;
`registration.py` turns a declaration document into that one transaction, with `merge.py`
(re-registration), `references.py` (what may not be withdrawn), `state.py` and `refusals.py`
beside it. Nothing here runs anything: a run is read from here and frozen by `flow/`.
"""
