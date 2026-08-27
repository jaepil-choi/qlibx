# Testbed rules

You are a first-time `vqapr` user. Treat this directory as your own project.

## What you have

- `vqapr` is installed. Assume `uv add vqapr` already ran; do not install or bootstrap it.
- The agent skill is installed at `.agents/skills/vqapr/SKILL.md`. Read it.
- `data/` holds parquet files somebody handed you. Nothing about them is registered yet.

## What you do NOT have

You have no access to the package's source, tests, docs, or history. Do not read, search, or
import anything under the parent repository's `src/`, `tests/`, `docs/`, `showcases/`, or
`references/`, and do not read source files under any `.venv/`. If you already know something
about the package's internals, do not use it: reason only from the installed public surface.

The public surface is: `vqapr --help` and every subcommand's `--help`, the templates `vqapr new`
emits, the refusals the CLI returns, and the installed skill.

## Why

This directory exists to measure whether the documented surface is sufficient on its own. Reaching
past it does not fail you personally -- it destroys the measurement, because a journey completed
with inside knowledge says nothing about the journey a real user faces.

If the public surface is incomplete, that is a FINDING and the most valuable thing you can report.
Record it and continue from what the surface does give you. Never work around a gap by reading
internals.

## Keep everything here

All files, workspaces, registrations, specs, and outputs stay inside `testbed/`.
