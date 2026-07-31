# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg?cacheSeconds=300)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)
[![By DolphinQuant](https://img.shields.io/badge/by-DolphinQuant-005f87)](https://dolphinquant.com)

> 📖 [English](README.md) · [简体中文](README.zh-CN.md)

> **An LLM-agent-native backtest framework for futures research.** LLM agents driving quantitative research is becoming routine, and the trajectory looks inevitable. For agents to drive strategy creation reliably, they need backtest tooling designed for them — typed tools they call directly, structured error codes they can resolve, an indicator catalog they can query. Without that, agents writing trading code from prose documentation hallucinate: wrong indicator names, made-up function signatures, params that don't exist. Echolon makes the framework itself the agent's API: 23 MCP tools, 22 in-package skills, 32 catalogued error codes, 214 indicators with typed metadata. End-to-end today: SHFE daily futures.

Production engine inside [Qorka](https://dolphinquant.com), [DolphinQuant](https://dolphinquant.com)'s AI-native strategy generation product. Exercised by real money on SHFE every trading day. 

## Quickstart

Three commands cover the natural newcomer arc:

| Command | Purpose | Time |
|---|---|---|
| `echolon hello` | Quick demo. Downloads SHFE aluminum (last 2y) via akshare, scaffolds a strategy, runs a backtest. Network required. | ~30s |
| `echolon init <workspace> --market SHFE --instrument <i> --start <d> --end <d> --template <t>` | Start a real project. Downloads market data via akshare (free, no signup), scaffolds a strategy from a template, writes a workspace marker. | ~1–5 min |
| `echolon backtest single <strategy_dir> [--json]` | Iterate after editing. Walks up to recover ctx from the workspace marker, recomputes indicators, runs the backtest. No flags needed. | ~5–10s |

```bash
pip install echolon
mkdir -p ~/echolon-playground && cd ~/echolon-playground
echolon hello                  # 30-second demo
```

`echolon hello` downloads ~2y of aluminum data, scaffolds the `momentum_breakout` template, writes `.echolon-workspace.json`, and runs the backtest. Open `./echolon-hello/strategy/baseline/entry.py`, tweak a parameter, then re-run with `echolon backtest single ./echolon-hello/strategy/baseline/` to see how the Sharpe shifts.

Three templates ship in-package — `minimal`, `momentum_breakout`, `rsi_mean_reversion`. `echolon examples --list` shows them; pass `--template <name>` to `echolon init` / `echolon hello` to start from one.

> **If `pip install` fails** on Linux ARM64 / Alpine / FreeBSD, run `echolon doctor` — it diagnoses ta-lib's C library, the only dependency that may need source-building outside the standard prebuilt-wheel platforms (Linux x86_64, macOS x86_64+arm64, Windows x86_64; Python 3.11–3.12).

## Drive it from your agent

```bash
pip install echolon                                # 1. install
claude mcp add -s user echolon -- echolon-mcp      # 2. register MCP server (user-wide)
# 3. restart Claude Code to load mcp__echolon__* tools
```

Then ask:

> "Build a trend-following strategy on copper, backtest 2018–2024."

Behind the scenes:

1. `list_skills` → picks `patterns` + `quick_start`
2. `load_template("momentum_breakout")` → 4-file scaffold
3. `list_indicators(has_lookback=True)` → picks an indicator
4. edits `entry.py` and `exit.py`
5. loops `validate_strategy_full(strategy_dir)` until clean
6. runs the backtest

On any error, parses `[CODE-NNN]` from the traceback → `get_error_doc(code)`. No step in the chain requires the agent to guess.

| Runtime | Setup |
|---|---|
| **Claude Code** | `claude mcp add -s user echolon -- echolon-mcp` |
| Cursor | In `~/.cursor/mcp.json` add an entry under `mcpServers`: `"echolon": {"command": "echolon-mcp", "args": []}` |
| OpenAI Codex CLI | `codex mcp add echolon -- echolon-mcp` (writes `[mcp_servers.echolon]` to `~/.codex/config.toml`) |
| OpenAI Agents SDK (Python) | `MCPServerStdio(name="echolon", params={"command": "echolon-mcp", "args": []})` |
| LangChain / LangGraph | [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/): `MultiServerMCPClient({"echolon": {"transport": "stdio", "command": "echolon-mcp", "args": []}})` |
| Any other [MCP-compatible](https://modelcontextprotocol.io/) client (CrewAI, AutoGen, …) | Configure it as a stdio server with `command="echolon-mcp"`, no args. See your client's MCP docs for the call shape. |

`-s user` registers Echolon for all your projects (drop it for current-project only); `--` separates the registration name from the launch command. After running once, `claude mcp list` should show `echolon` as connected. The agent's orientation guide is [`llms.txt`](./echolon/llms.txt) — also dropped at the workspace root by `echolon init` / `hello`, so any agent walking into the project finds it without needing the package.

## What's in scope today

**Done end-to-end** (production-grade, exercised daily):
- SHFE daily futures research — data ingestion, 214-indicator catalog, Backtrader execution, Optuna TPE optimization (single + multi-objective), walk-forward analysis with deployment-readiness scoring, KMeans-based robust trial selection.
- Agent surface — 23 MCP tools, 22 skills, 32 error codes, 3 working templates.

**Not yet** (open an issue if you want to drive a slice forward):
- SHFE intraday backtesting — data pipeline ready, engine plumbing being firmed up.
- Live trading via MiniQMT — clean public release in progress.
- Crypto perpetuals (CCXT adapter scaffolded), CME futures, equities.
- Optuna alternatives (no grid, no random, no Bayesian-budget search), distributed orchestration, Python ≤ 3.10.
- Pre-1.0 — public API may change between minor versions. Breaking changes documented in [CHANGELOG.md](./CHANGELOG.md).

## Bring your own data

If you already have raw SHFE XLS files (downloaded from shfe.com.cn), run `SHFEFileDayExtractor` directly instead of using akshare. For other formats (broker CSV, tushare, custom DB), three files must end up under `{workspace}/workspace/data/market_data/SHFE/{instrument}/`:

| File | Schema |
|---|---|
| `sort_by_contract/{contract}.csv` | `contract, date, prev_close, prev_settlement, open, high, low, close, settlement, price_change, settlement_change, volume, turnover, open_interest` |
| `sort_by_date.csv` | Same columns, all rows concatenated and sorted by date. |
| `trading_calendar.csv` | `date, is_trading_day` (boolean). |

Plus under `{workspace}/data/SHFE/{instrument_code}/` (note the SHORT code, e.g. `al` not `aluminum`):

| File | Schema |
|---|---|
| `main_contract.csv` | `date, main_contract` where `main_contract` is the contract code with `.SF` suffix (e.g. `al2401.SF`). One row per change-of-main-contract date. |

Echolon does **not** auto-derive `main_contract.csv` from raw OHLCV — it's a USER input that encodes your roll convention (rules based on volume, open interest, or days to expiry). For SHFE via akshare, `echolon init` derives it for you; otherwise produce it yourself and drop it in place.

## Project info

Apache 2.0 — see [LICENSE](LICENSE). Use freely, commercially or otherwise. Active development, v0.1.3 beta. Built and maintained by [DolphinQuant](https://dolphinquant.com) — the same team running Qorka on SHFE. Issues and pull requests welcome at [github.com/DolphinQuant/echolon](https://github.com/DolphinQuant/echolon).

```bibtex
@software{echolon,
  title = {Echolon: AI-native quantitative trading engine},
  author = {DolphinQuant},
  year = {2026},
  url = {https://github.com/DolphinQuant/echolon},
}
```
