# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg?cacheSeconds=300)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)
[![By DolphinQuant](https://img.shields.io/badge/by-DolphinQuant-005f87)](https://dolphinquant.com)

> 📖 [English](README.md) · [简体中文](README.zh-CN.md)

> **专为 LLM Agent 设计的期货研究回测框架**。自带 MCP 服务器、22 个内置 skill、32 个分门别类的错误码、带类型的 Pydantic 配置 — Agent 调的是结构化工具,不用对着大段文字描述硬猜 API。SHFE 日线期货端到端可用。

[Qorka](https://dolphinquant.com)([DolphinQuant](https://dolphinquant.com) 旗下的 AI 原生策略生成产品)的内部研究引擎,每个交易日都在 SHFE 上进行实盘交易。

## 快速上手

三条命令对应新用户的自然上手顺序:

| 命令 | 用途 | 耗时 |
|---|---|---|
| `echolon hello` | 看一眼效果。用 akshare 下载近 2 年的 SHFE 铝期货数据,搭策略骨架,跑回测,需要联网。 | ~30 秒 |
| `echolon init <workspace> --market SHFE --instrument <i> --start <d> --end <d> --template <t>` | 起一个真实项目。用 akshare 拉行情(免费,不用注册),从模板生成策略骨架,写入工作区标记。 | ~1–5 分钟 |
| `echolon backtest single <strategy_dir> [--json]` | 改完再跑。一路向上找工作区标记并自动恢复上下文,重算指标,跑回测。一个参数都不用传。 | ~5–10 秒 |

```bash
pip install echolon
mkdir -p ~/echolon-playground && cd ~/echolon-playground
echolon hello                  # 30 秒看效果
```

`echolon hello` 会下载近 2 年的铝期货数据,基于 `momentum_breakout` 模板搭好策略,写入 `.echolon-workspace.json`,然后立刻跑一次回测。打开 `./echolon-hello/strategy/baseline/entry.py` 改一个参数,再用 `echolon backtest single ./echolon-hello/strategy/baseline/` 跑一次,就能看到 Sharpe 怎么变。

包内自带三套模板 — `minimal`、`momentum_breakout`、`rsi_mean_reversion`;`echolon examples --list` 可以列出来。`echolon init` / `echolon hello` 后面加 `--template <name>` 就能从对应模板起步。

> **`pip install` 装不上?** Linux ARM64 / Alpine / FreeBSD 等平台跑一下 `echolon doctor` — 它会指出 ta-lib 的 C 库少了什么(标准平台之外唯一可能要从源码编译的依赖;标准平台是 Linux x86_64 / macOS x86_64+arm64 / Windows x86_64,Python 3.11–3.12)。

## 在 Agent 里驱动它

```bash
pip install echolon                                # 1. 安装
claude mcp add -s user echolon -- echolon-mcp      # 2. 注册 MCP 服务器(用户级,所有项目都能用)
# 3. 重启 Claude Code 会话,加载 mcp__echolon__* 工具
```

然后直接发指令:

> 「在铜上做一个趋势跟随策略,回测 2018–2024」

背后实际发生的事:Agent 调 `list_skills` → 挑出 `patterns` 和 `quick_start` → 调 `load_template("momentum_breakout")` → 调 `list_indicators(has_lookback=True)` 看可用指标 → 改 `entry.py` 和 `exit.py` → 反复调 `validate_strategy_full(strategy_dir)` 直到全部通过 → 跑回测。中途出错就从 traceback 里解析 `[CODE-NNN]`,调 `get_error_doc(code)` 查文档。整个流程没有一处需要它瞎猜。

| 运行时 | 配置方式 |
|---|---|
| **Claude Code** | `claude mcp add -s user echolon -- echolon-mcp` |
| Cursor | 在 `~/.cursor/mcp.json` 的 `mcpServers` 下加一条:`"echolon": {"command": "echolon-mcp", "args": []}` |
| OpenAI Codex CLI | `codex mcp add echolon -- echolon-mcp`(会在 `~/.codex/config.toml` 里写入 `[mcp_servers.echolon]`) |
| OpenAI Agents SDK (Python) | `MCPServerStdio(name="echolon", params={"command": "echolon-mcp", "args": []})` |
| LangChain / LangGraph | [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/):`MultiServerMCPClient({"echolon": {"transport": "stdio", "command": "echolon-mcp", "args": []}})` |
| 其他[兼容 MCP](https://modelcontextprotocol.io/) 的客户端(CrewAI、AutoGen 等) | 按 stdio 服务器配置,`command="echolon-mcp"`,不需要 args。具体调用形式参见所用客户端的 MCP 文档。 |

Claude Code 注意:`-s user` 把注册写到用户级,所有项目都能用(去掉它就只对当前项目生效);`--` 把注册名和启动命令分开。注册一次后跑 `claude mcp list` 应该能看到 `echolon` 是已连接的 stdio 服务器。Agent 的入门导引在 [`llms.txt`](./echolon/llms.txt) — `echolon init` / `hello` 也会把副本写到 workspace 根目录,这样 Agent 即便没接 MCP 也能在本地找到。

## 当前的能力范围

**端到端可用**(生产级,每天都在跑):
- SHFE 日线期货研究 — 数据采集、214 个指标的目录、Backtrader 引擎、Optuna TPE 优化(单目标和多目标都支持)、带部署就绪打分的滚动窗口分析(walk-forward analysis)、基于 KMeans 的鲁棒试验筛选。
- Agent 接入层 — 23 个 MCP 工具、22 个 skill、32 个错误码、3 个能跑的策略模板。

**还没做**(想推哪一块,提个 issue):
- SHFE 日内回测 — 数据管线已经支持,引擎那一边还在收尾。
- 通过 MiniQMT 实盘 — 公开版本正在重写。
- 加密货币永续合约(CCXT 适配器骨架已经有了)、CME 期货、股票。
- Optuna 之外的优化策略(没有网格搜索、随机搜索,也没有带预算控制的贝叶斯优化)、分布式编排、Python 3.10 及以下。
- 1.0 之前 — 公共 API 在 minor 版本之间可能会变。Breaking changes 都会记到 [CHANGELOG.md](./CHANGELOG.md)。

## 用自己的数据

如果你已经有原始的 SHFE XLS 文件(从 shfe.com.cn 下载的),直接用 `SHFEFileDayExtractor` 替掉 akshare 那一路就行。如果是别的格式(券商 CSV、tushare、自建数据库等),按下面的约定把三个文件落到 `{workspace}/workspace/data/market_data/SHFE/{instrument}/` 下:

| 文件 | Schema |
|---|---|
| `sort_by_contract/{contract}.csv` | `contract, date, prev_close, prev_settlement, open, high, low, close, settlement, price_change, settlement_change, volume, turnover, open_interest` |
| `sort_by_date.csv` | 列同上,把所有合约的行合在一起按日期排序。 |
| `trading_calendar.csv` | `date, is_trading_day`(布尔)。 |

外加一份在 `{workspace}/data/SHFE/{instrument_code}/` 下(注意这里是**短代码**,例如 `al` 而不是 `aluminum`):

| 文件 | Schema |
|---|---|
| `main_contract.csv` | `date, main_contract`,其中 `main_contract` 是带 `.SF` 后缀的合约代码(例如 `al2401.SF`)。每次主力换月一行。 |

Echolon **不会**从原始 OHLCV 自动推导 `main_contract.csv` — 这份文件算作**用户输入**,里面写的是你自己的换月规则(成交量 / 持仓量 / 离到期日多少天之类的逻辑)。走 SHFE + akshare 这条路时,`echolon init` 会替你推一份;其他情况下请自己产出这个文件,放到上面的位置。

## 项目信息

Apache 2.0 — 见 [LICENSE](LICENSE)。可自由使用,商用非商用都行。活跃开发中,v0.1.3 beta。由 [DolphinQuant](https://dolphinquant.com) 开发并维护 — 同一支团队在 SHFE 上运营 Qorka。欢迎到 [github.com/dolphinquant/echolon](https://github.com/dolphinquant/echolon) 提 issue 和 pull request。

```bibtex
@software{echolon,
  title = {Echolon: AI-native quantitative trading engine},
  author = {DolphinQuant},
  year = {2026},
  url = {https://github.com/dolphinquant/echolon},
}
```
