# quant-agents (QRAFTI) upstream snapshot

- Source: https://github.com/terence-lim/quant-agents
- Branch at import: `main`
- Commit: `0760c453287c025960bf278d2970557c88cb9de9`
- Imported on: 2026-08-26
- Local path: `references/quant-agents/`

All 48 paths tracked by the upstream repository at the commit above were
imported without modification. Git metadata is intentionally excluded so this
directory is ordinary, non-authoritative reference content in the qlibx
repository. This is a plain download, not a Git submodule. The upstream
`LICENSE` (MIT) is included at `references/quant-agents/LICENSE`.

The clone was taken with `core.autocrlf=false`, and every imported blob was
verified to hash identically to its upstream counterpart, so the working tree
holds the upstream bytes exactly. No imported path is hidden by the upstream
`.gitignore` or the qlibx root `.gitignore`, so no re-include rules were
needed.

`Internet_Appendix.pdf` is 38 MB — by far the largest file in the snapshot, and
larger than any other single file under `references/`. It is kept because
`README.md` links to it for the full agent conversation histories and traces,
and those citations must remain resolvable from the repository alone.

## Local metadata added outside the upstream snapshot

- `UPSTREAM.md` — this file.
- `.gitattributes` — `* -text`, to preserve imported blobs byte-for-byte.
  Upstream ships no `.gitattributes`, and without this the parent repository
  rewrites every LF file to CRLF on checkout.

## Why this reference

QRAFTI is a multi-agent framework for empirical factor research: MCP tool
servers (`research_server.py`, `report_server.py`, `coding_server.py`) expose
panel-data and factor-construction operations as callable tools, and
Pydantic-AI agents (`shared_agents.py`, `agent_delegation.py`) drive factor
research, standardized reporting, and code execution over them. `tests/`
carries the replication queries for Fama-French HML and JKP-style momentum,
which is the same replication ground as `references/jkp-data/`.

Its interest for qlibx is the tool-server boundary: what an agent is allowed to
ask for, in what vocabulary, and how a factor definition is carried between
agents. Paper: Lim, Muthuraman & Sury (2026), *QRAFTI: An agentic framework for
empirical research in quantitative finance*, https://arxiv.org/abs/2604.18500.
As with everything under `references/`, it is non-authoritative: nothing here
constrains qlibx design unless the project manifest explicitly promotes a file.
