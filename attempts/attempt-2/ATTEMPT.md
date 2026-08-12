# Attempt 2

Status: archived reference
Source branch: `exp/2nd-attempt`
Source branch HEAD before archival: `fda103785bbc7503c26d5f9cd243d6f6ea3d6f73` (the concurrent commit changed only retained `docs/vqapr-architecture.md`)
Qlibx material baseline commit: `11a7b91e`
Archived on: 2026-08-12

This directory preserves the second qlibx implementation as historical engineering evidence before
the repository root is renamed and rebuilt as `vqapr`.

The archive includes:

- `src/`, containing the second implementation;
- `tests/`, `experiments/`, and `showcases/`, containing its validation and demonstrations;
- `docs/`, containing qlibx-era product, architecture, review, handoff, research, and implementation
  records;
- the original `.gitignore`, `.python-version`, `README.md`, `pyproject.toml`, and `uv.lock`.

The newer root `docs/vqapr-prd.md` and `docs/vqapr-architecture.md`, reusable agent/workflow
infrastructure, external `references/`, shared/local data, environments, caches, and unrelated
runtime state remain outside this archive.

Classification evidence:

- `src/`, `showcases/`, and `tests/` were modified and committed through 2026-08-11, so they are
  attempt-2 artifacts rather than stale attempt-1 duplicates;
- `experiments/` and qlibx-era documents were also updated during attempt 2;
- ignored `qlibx-research/` had no tracked files and no update after 2026-07-27, so it was removed
  as obsolete generated runtime state instead of being archived.

Attempt 2 is frozen. Do not implement new behavior here. Use it only as comparative evidence for
the `vqapr` design and implementation.
