# vqapr

**v**ibe **q**uant **a**sset **p**ricing / **a**lpha **p**ortfolio **r**esearch — a reusable alpha
research framework that owns its own research and execution capability.

- Product authority: [`docs/vqapr-prd.md`](docs/vqapr-prd.md)
- Structure: [`docs/vqapr-architecture.md`](docs/vqapr-architecture.md)

## Install

```
uv add vqapr
```

## Commands

`vqapr` is one CLI over a workspace directory. Every verb reads declarations and writes derived
state under `.vqapr/`, which is rebuildable and never committed.

| command | what it does |
|---|---|
| `new` | scaffold a component, or emit a dataset/agendas/run declaration template |
| `register` | validate a declaration and add what it declares to the workspace |
| `check` | prove a registered run is ready, reporting every problem at once, without running |
| `run` | freeze a registered run, preflight it, and execute its strategies |
| `list` | show what the workspace holds and what the store recorded |
| `show` | answer questions about one run or one strategy record, from what was frozen |
| `rm` | remove a run's records, or withdraw a registration nothing still names |
| `skill` | install the agent skill into this project, or remove and inspect it |

Run `vqapr <command> --help` for the arguments of any verb.

## Repository layout

| path | contents |
|---|---|
| `src/vqapr/` | the package |
| `tests/` | the test suite |
| `docs/` | PRD, architecture, implementation records, handoffs |
| `showcases/` | end-to-end demonstrations |
| `scripts/` | evidence and fixture-preparation scripts, not part of the distribution |
| `testbed/` | a measurement workspace treated as a first-time user's project, not as source |
| `references/` | vendored upstream snapshots — non-authoritative unless the project manifest promotes a file |
| `attempts/` | frozen earlier implementations, kept for their record and not maintained |

## Prior implementations

This package was previously named `qlibx`. Its first and second implementations are frozen under
[`attempts/attempt-1/`](attempts/attempt-1/) and [`attempts/attempt-2/`](attempts/attempt-2/), and
are archives rather than supported code.

Attribution for third-party arithmetic is in [`NOTICE`](NOTICE).
