"""Running a run: before it starts, the loop, and what it leaves behind.

`preflight/` judges a declaration and freezes it; `engine/` is the loop -- the two clocks, the
stages the wiring table puts on them, the state a run accepts and the evidence it leaves. Beside
them, `assemble.py` builds one run and publishes what it made, `batch.py` runs several at once
(`--jobs`), `recording.py` turns a finished run into its record, and `roster.py` reads the
instrument roster a run declared.

No re-export: import the module (record `192`'s convention).
"""
