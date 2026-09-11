"""The extension point: every role a user's code can play, and the door it enters by.

One module per role, each base apart from any shipped implementation: `datamodel.py`, `strategy/`,
`exchange/`, `compliance/`. `base.py` is what every role is (`Component`, `Part`, `Tool`). The door
is `reference.py` (what a registration names), `fingerprint.py`, `loading.py`, `conformance.py`
(prove a class plays its role) and `scaffold.py` (what `vqapr new` writes). Nothing here imports
above the subject packages; the engine that calls a component back lives in `flow/`.
"""
