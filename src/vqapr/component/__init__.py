"""The extension point: every role a user's code can play, and the door it enters by.

One module per role, each base apart from any shipped implementation: `datamodel.py`, `strategy/`,
`exchange/`, `compliance/`. `base.py` is what every role is (`Component`, `Part`, `Tool`) and what
every role is handed (`Call`). The door is `reference.py` (what a registration names),
`fingerprint.py`, `loading.py` and `conformance.py` (prove a class plays its role).

Nothing here imports above the subject packages. The engine that calls a component back lives in
`run/engine/`; the templates `vqapr new` writes live in `agent/scaffold.py`.
"""
