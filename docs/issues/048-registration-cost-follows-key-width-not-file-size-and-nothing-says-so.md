# 048 — Registration cost follows `rows x key_fields`, not file size, so the guidance that says to keep vendor grain does not mention that it triples the bill

**Status when filed:** open, and **low severity by design** — this is a documentation gap with a
measured basis, not a defect. Found 2026-08-31 in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel).
**Touches:** `src/vqapr/data/scan.py:492` (`key_check`); `src/vqapr/data/datasets.py:275`
(`validate`, whose docstring already separates the three phases); `SKILL.md`'s registration
paragraph.

## The measurement

Every dataset a real research environment declares, each registered into its own empty workspace,
in-process through `vqapr.public.register_dataset` so no subprocess startup is counted:

| dataset | file | rows | key fields | wall | of which `key_check` |
|---|---|---|---|---|---|
| `equity-daily` | **449.9 MB** | 8,651,872 | 2 | **0.43 s** | 0.39 s |
| `consensus-daily` | 54.9 MB | 9,727,752 | 5 | 0.61 s | 0.57 s |
| `valuation-daily` | 49.9 MB | 5,941,113 | 2 | 0.23 s | 0.20 s |
| `statement-facts` | 84.0 MB | 37,838,635 | 6 | **5.54 s** | 5.49 s |
| twenty datasets, total | 713 MB | 82.3M | — | 8.1 s | — |

**The 450 MB file registers thirteen times faster than the 84 MB one.** Bytes are not the axis.
Across the eleven datasets large enough to measure, `rows x key_fields / wall` lands between 40M and
80M per second, and the schema read (`describe`) and the workspace write are flat at ~20 ms and
~5 ms regardless of size. Registration is `key_check`, and `key_check` is a distinct-count whose
width is the logical key.

`validate`'s own docstring already says this — schema, then key, then span, with the last two marked
전체 스캔. The cost model is correct and stated in the source. It is simply not stated anywhere the
person choosing a key will read it.

## Why it is worth saying out loud

The package tells authors, correctly, not to collapse a vendor's grain. `vqapr-enhanced-index-3`
follows that and registers `statement-facts` on six key fields — `available_at`, `instrument`,
`account_code`, `statement_scope`, `settlement_type`, `fiscal_period` — because choosing among a
name's many rows on one date is the research's decision.

That choice tripled its registration cost against a two-key alternative. **That is the right choice
anyway**, and 5.5 seconds paid once is not a reason to reconsider it. But it is a decision a user
makes with a cost attached, and right now they make it blind, then meet the cost as a surprise on a
file they will reasonably suspect is slow because it is large. The `--reset` rebuild pays it again
every time.

## What to say, and where

One line beside the key-fields guidance: **registration reads the file once per declared logical
key; the cost scales with rows x key width and not with file size, at roughly 50M row-keys per
second.** A user can then price their own grain decision, and — more usefully — stops looking for
the slowness in the wrong place.

## What not to do

**Do not optimise `key_check`.** 8.1 seconds for a twenty-dataset warehouse, paid once per
workspace, is not a bottleneck; the same profiling pass that produced this file found the two that
are ([044](044-the-read-path-revalidates-eight-column-names-once-per-row.md),
[046](046-a-factor-book-pays-per-callback-and-each-declared-input-costs-two-queries.md)), and both
are on the read path, which runs thousands of times more often. This file exists so that
registration is *ruled out* with a number rather than left as a suspicion.
