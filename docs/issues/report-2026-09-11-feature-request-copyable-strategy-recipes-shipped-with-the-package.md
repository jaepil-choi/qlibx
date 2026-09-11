# Feature request: copyable strategy recipes shipped with the package, emitted by `vqapr new strategy`

**Kind: feature request.**

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.4` wheel for the runs; the CLI and skills were re-checked on develop `173f8c7e` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, runs `B-1` (opus 5), `B-2` (sonnet 5), `B-3` (haiku 4.5) |
| related | `report-2026-09-11-adding-one-strategy-to-an-existing-workspace-still-costs-agents-more-than-a-pandas-project.md` (the measurement this request answers) |

## The problem it solves

Adding one strategy to an existing workspace cost agents 1.8x (opus) to 3.8x (sonnet) what the
same task cost in a pandas project. Most of the extra went to reading the authoring API by hand.
B-1 read 82 KB of `--help`, `dir()` and pydoc output, and B-2 made 11 `help()` calls returning 46 KB.
That text stays in context, so every later turn pays for it again.

All three agents needed the same five pieces, and each wrote them from scratch:

| piece | B-1 | B-2 | B-3 |
|---|---|---|---|
| read two datasets: prices through `matrix()`, index weights through `current()` | yes | yes | yes |
| carry positions across callbacks in `self.memory` (entry price, side, pending fills) | yes | yes | no |
| write an event log of its own with `TableSpec` and `self.recorder.append` | yes | yes | no |
| return daily weights with a cash share: `Rebalance.of(long=, invested=)` or `Rebalance.signed(gross=)` | yes | yes | yes |
| a daily decide-and-fill clock that `check` accepts | 15:29 on the fill day | 15:31 on t; see the fill-window report | 15:29 |
| strategy file length | 178 lines | 266 lines | 181 lines |

## What exists today, and why it did not help

- **`vqapr new strategy` scaffolds one read and one `Rebalance`.** B-1 and B-2 both ran it and then
  went to pydoc for the rest.
- **The shipped sample (`vqapr new sample`) is a 5-day reversal over one synthetic dataset.** It
  uses no memory, no table of its own and no second dataset.
- **The repository's `showcases/` are not in the wheel.** The wheel ships only `src/`, so an agent
  working from the installed package cannot reach them, and no skill mentions them.
  `show_005_enhanced_index` is also a demonstration of framework claims, using `optimize`, a
  published alpha and four names. It is not something to copy and edit.

## Proposal

Ship a small set of recipes inside the package, each a complete component plus its run
declaration, which register and run against a workspace like the testbed's. `vqapr new strategy
<id> --recipe <name> --dataset ...` would emit one. The `make-strategy` skill would list them
first, before the API references. Recipes the testbed would have used:

1. **Daily weights over two datasets.** Prices plus a benchmark-weight dataset, index weight as
   the base, a per-name tilt, and the whole book scaled to an invested share.
2. **Positions with state.** Entries and exits carried in `self.memory`, with an entry price and
   take-profit or stop-loss exits judged at each callback.
3. **An event log table.** A `TableSpec` and `self.recorder.append` for entries and exits, and how
   to join it with `vqapr.fill` for fill-dependent facts such as the fill price.
4. **The two daily clocks.** "Decide before the close, fill at the close" (15:29 / 15:30), and
   "decide after the close, fill at the next close". The second would come with the `within` and
   `end` values that `check` accepts; see the fill-window report.

Zero-weight handling belongs in recipe 1, whichever way `Rebalance.of` ends up treating a zero.

## How the rerun will measure it

The testbed will rerun the same six cells once the recipes ship. Success means three things:

- B's API-reading output falls well below today's 46–82 KB per run.
- B's cost ratio to A falls from today's 1.8x (opus) and 3.8x (sonnet).
- Accuracy stays where it is. Today opus is exact and sonnet is exact on NAV.
