# JKP Data upstream snapshot

- Source: https://github.com/bkelly-lab/jkp-data
- Branch at import: `main`
- Commit: `6fb206b42b5778ba0a1d12e3fec0c23ac6b1c251`
- Imported on: 2026-08-13
- Local path: `references/jkp-data/`

All 246 paths tracked by the upstream repository at the commit above were
imported without modification. Git metadata is intentionally excluded so this
directory is ordinary, non-authoritative reference content in the qlibx
repository. The upstream `LICENSE` and `DATA_LICENSE` files are included at
`references/jkp-data/`.

The clone was taken with `core.autocrlf=false` so the working tree holds the
upstream blobs byte-for-byte.

## Local metadata added outside the upstream snapshot

- `UPSTREAM.md` — this file.
- `.gitattributes` — `* -text`, to preserve imported blobs byte-for-byte.
- `documentation/compustat_correction/data/.gitignore` — re-includes the
  upstream-tracked `correction_factor_stats.parquet` file that the upstream
  root `.gitignore` would otherwise hide from the parent repository once the
  original Git index is removed.
