# Security Policy

## Supported versions

Only the latest published version on PyPI receives security fixes. Pre-1.0, that means we ship fixes in the next minor or patch release rather than backporting.

| Version | Status |
|---|---|
| 0.1.x | supported |
| < 0.1.0 | not supported (pre-public, never published) |

## Reporting a vulnerability

**Do not file public issues for security problems.**

Email <zongjiany@outlook.com> with:

- A description of the vulnerability and its impact.
- Steps to reproduce — minimal example preferred.
- The version of `echolon` where you observed it (`echolon --version`).
- Whether the issue affects the CLI, the MCP server, or library code paths specifically.

We aim to respond within 7 days and release a fix within 30 days for confirmed vulnerabilities. We will credit you in the CHANGELOG entry unless you prefer to remain anonymous.

## Scope

In scope:
- Code execution paths in the library and CLI.
- The MCP server (`echolon-mcp`) — particularly tools that touch user-provided strategy code or filesystem paths.
- Strategy code loading (`StrategyLoader`) and validators that dynamically import or evaluate user-provided strategy modules — these are intentional but bounded; report any escape from the intended boundary.
- Path-handling in `PathsConfig` and host-app workspace markers.

Out of scope:
- Issues in transitive dependencies (report those upstream — `ta-lib`, `backtrader`, `optuna`, `akshare`, `pydantic`, `mcp`).
- Trading strategy outcomes (P&L, drawdown). Backtests are not investment advice; live deployment is at your own risk.
- Vulnerabilities that require an attacker to already have local code execution as the user running echolon.
