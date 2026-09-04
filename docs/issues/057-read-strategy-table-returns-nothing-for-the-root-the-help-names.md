# 057 -- `read_strategy_table` returns an empty iterator for the root the help names and for the `strategy_ref` the signature allows

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: `read_table` refuses a missing run or ref with `RunRecordMissing` naming the directory looked in and what is beside it; a bare `<strategy-id>` and `None` resolve to the only record; the docstring, `--store-root`'s help and the skill say the root is the `store_root` `run` prints.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-007** and the urge entry **F-012**), against
`vqapr-0.3.0`. Confirmed against source the same day.

**Touches:** `src/vqapr/flow/run_records.py:1027-1038` (`read_table`, the bare `return` on a
missing path) and `:767-772` (`record_directory`); `src/vqapr/cli/run.py:186-190` (`--store-root`
help); `src/vqapr/agent/skill/SKILL.md:173-180`.

## What happens

The skill documents the reader as `read_strategy_table(store_root, run_id, table, strategy_ref)`
and `vqapr run --store-root` says the default is *"the workspace directory"*. The user passed the
project root. Three empty DataFrames came back and their own code failed downstream. No refusal,
no *"no such run under <path>"*.

Probing nine `(root, strategy_ref)` combinations showed rows come back **only** for root
`<project>/.vqapr` **and** the full `<strategy-id>@<fp8>` ref. `strategy_ref=None`, which the
signature types as allowed, and the bare `<strategy-id>`, which the CLI accepts when one record
exists, both return an empty iterator silently. The run result's own `store_root` field says
`...\.vqapr`, which is what finally worked.

This is the entry where the agent wanted to open `flow/run_records.py` (F-012): two undocumented
conventions and a silent failure on both is exactly the situation a user reaches for the source.

## Why

`read_table` does `if not path.is_file(): return`. `record_directory(root, run_id, None)` resolves
to the pre-`139` run-directory shape, which a `0.3.0` run never writes, so `None` is a valid
argument that can never find anything on a current record. Two names -- `store_root` in the
skill, "workspace directory" in the help -- describe one path neither spells out.

## What to do

- Refuse when `root / runs / run_id` does not exist, naming the directory looked in and the run
  ids found beside it; refuse when `strategy_ref` names no directory, listing the refs present.
- Resolve the bare `<strategy-id>` the way the CLI does when one record exists.
- Say in the docstring and the skill that the root is the `store_root` `vqapr run` prints
  (`<project>/.vqapr`), and make `--store-root`'s help say the same words.
