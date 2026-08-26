# Vibe-Trading upstream snapshot

- Source: https://github.com/HKUDS/Vibe-Trading
- Branch at import: `main`
- Commit: `5cd08ee1bd5c28e856b20acae3d077ed9bd919ce`
- Imported on: 2026-08-26
- Local path: `references/vibe-trading/`

2366 of the 2368 paths tracked by the upstream repository at the commit above
were imported without modification; the two exclusions are listed below. Git
metadata is intentionally excluded so this directory is ordinary,
non-authoritative reference content in the qlibx repository. This is a plain
download, not a Git submodule. The upstream `LICENSE` (MIT) and `NOTICE` are
included at `references/vibe-trading/LICENSE` and
`references/vibe-trading/NOTICE`.

The clone was taken with `core.autocrlf=false`, and every imported blob was
verified to hash identically to its upstream counterpart, so the working tree
holds the upstream bytes exactly.

## Import scope

Excluded from the snapshot:

- `assets/Frontend.mp4` (16 MB) and `assets/cli.mp4` (10 MB) — demo recordings.
  Upstream tracks them from before it added `assets/*.mp4` to its own
  `.gitignore` with the note "too large for git; link to external host
  instead". They carry no reference value for qlibx, so the upstream intent is
  honoured here rather than the upstream index.

Nothing else was dropped: no imported path is hidden by the upstream
`.gitignore`, `agent/.gitignore`, `frontend/.gitignore`, or the qlibx root
`.gitignore`, so no re-include rules were needed.

## Local metadata added outside the upstream snapshot

- `UPSTREAM.md` — this file.
- `.gitattributes` — `* -text`, to preserve imported blobs byte-for-byte.
  Upstream ships no `.gitattributes`, and without this the parent repository
  rewrites every LF file to CRLF on checkout.

## Why this reference

Vibe-Trading is an agent-first trading stack: Claude-Code-style skills under
`agent/src/skills/`, a factor zoo under `agent/src/factors/` (including a
Qlib Alpha158 port), backtesting, shadow accounts, and a broker kill-switch.
It is the closest public example of the agent-authored-strategy shape qlibx is
working towards, and its skill and factor layouts are worth reading against
`.agent/` and the qlibx declaration contracts. As with everything under
`references/`, it is non-authoritative: nothing here constrains qlibx design
unless the project manifest explicitly promotes a file.
