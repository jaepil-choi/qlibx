# Qlib upstream snapshot

- Source: https://github.com/microsoft/qlib
- Branch at import: `main`
- Commit: `79633dd9506ea689e5400dea0197717b5b3d74b7`
- Imported on: 2026-08-03
- Local path: `references/qlib/`

All 619 paths tracked by the upstream repository at the commit above were
imported without modification. Git metadata is intentionally excluded so this
directory is ordinary, non-authoritative reference content in the qlibx
repository. The upstream `LICENSE` (MIT) is included at
`references/qlib/LICENSE`.

The clone was taken with `core.autocrlf=false` so the working tree holds the
upstream blobs byte-for-byte. Upstream ships no `.gitattributes`, so a local one
is added here to keep the parent repository from applying line-ending
conversion to the imported files.

## Import scope change

This snapshot replaces an earlier partial import of the same commit that
carried only `README.md`, `docs/` and `examples/` (274 files). The full source
tree is now vendored because `docs/qlibx-architecture.md` cites specific
implementation locations in `qlib/backtest/`, `qlib/strategy/` and
`qlib/contrib/strategy/`, and `pyqlib` is no longer a project dependency. Those
citations must remain resolvable from the repository alone.

## Local metadata added outside the upstream snapshot

- `UPSTREAM.md` — this file.
- `.gitattributes` — `* -text`, to preserve imported blobs byte-for-byte.
- `examples/.gitignore` — re-includes eight upstream-tracked paths that the
  upstream root `.gitignore` (`*.ipynb`, `*.pkl`) would otherwise hide from the
  parent repository once the original Git index is removed.
- `Qlib_An_AI_oriented_Quantitative_Investment_Platform_Yang_et_al_(2020).pdf`
  — the Qlib paper. Not part of the upstream repository; carried over from the
  earlier import.

## Relationship to `pyqlib` 0.9.7

qlibx previously depended on `pyqlib==0.9.7` and the borrow analysis was read
from that wheel. The wheel and this commit were compared file by file across
the ten modules qlibx cites:

- Identical: `backtest/{exchange,position,account,decision,executor,report,utils}.py`,
  `strategy/base.py`, `contrib/strategy/signal_strategy.py`.
- One difference: `contrib/strategy/order_generator.py` gains a blank line at
  line 7, shifting every subsequent line by +1.

Line references in qlibx documents are stated against **this snapshot**.
