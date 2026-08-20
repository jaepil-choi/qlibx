# Handoff — conformance suite, version, and the CLI declaration surface

Status: in_progress
Branch: `jaepil-develop` · last commit `5449ad0` · **tree is green: 594 passed, ruff clean**
**Nothing is uncommitted.** Version is now `0.1.0a8`.

Supersedes `2026-08-20-testbed-gap-closure.md`, which is fully closed (B7, A3, B8 all resolved —
B8 was withdrawn as a false finding; read that file's top section before acting on any older copy).

The user asked for items **1 → 4 → 2** from a decision list. 1 and 4 are done. **2 is half done and
is where you pick up.**

---

## Resume here: item 2, second half

`register` now takes all four extension points (`5449ad0`). What still has **no CLI path at all**:

```
register: ('datamodel', 'strategy', 'constraint', 'exchange')     <- all four, done
list    : datasets · sources · components · agendas · execution-inputs
          strategy-configs · valuation-configs · monitoring-policies

no CLI path: datasets, sources, agendas, execution-inputs,
             strategy-configs, valuation-configs, monitoring-policies
```

**A runnable workspace still cannot be reached through the CLI alone.** `tests/cli/test_commands.py`
proves this: its `_workspace_for_run` fixture registers those seven through the library because no
command exists. That is the remaining gap, not a workaround.

This matters more since `85649a5`: an execution input is now **mandatory** for every run, and there
is no `vqapr register execution-input`.

### The split I would make

Three of the seven are trivial — a component id plus an agenda id — and fit argv directly:

```
vqapr register strategy-config   <component-id> <agenda-id>
vqapr register valuation-config  <agenda-id>
vqapr register monitoring-policy <agenda-id>
```

The other four carry structure (field maps, key fields, fill conventions) that does not fit flags.
They want a small YAML projection, the same shape `run` already uses for `spec.yaml`:

- `dataset` — `DatasetRegistration.of(...)` + its `SourceSpec`. Note these register **together**
  (`workspace.register_dataset(registration, source)`), so one command covers dataset *and* source.
- `execution-input` — `ExecutionInputRegistration.of(...)` with `ExecutionTableSpec` +
  `FillConvention`.
- `agenda` — `OperationAgenda`. Check `OperationAgenda.daily()` first (`6c74f4e`); it may already
  cover the common case from a dataset's own sessions, which would make this a thin command.

Follow `cli/run.py`'s existing shape: a `_REQUIRED` tuple checked **before** anything is opened,
each piece built by a small `_thing(document)` helper, and no re-implementation of the invariants
the registration objects already enforce in `__post_init__`.

---

## Done this session

| commit | what | evidence |
|---|---|---|
| `e5ce32e` | B7 — `rescale(..., grid=)` | quantize first, settle second. Three equal names quantized *after* rescaling sum to `0.99`; with `grid=` they sum to `1.00` and stay on the grid |
| `43ca56f` | A3 — CLI answers in one shape, `run` proven to run | `occurrences=12, account_version=7`, both pinned. argparse was escaping the envelope with an empty stdout |
| `85649a5` | execution price required where run-readiness is decided | preflight promised "run-ready" and returned a `FrozenRun` that `run()` always rejects; two validations were being skipped entirely |
| `dc435fd` | **item 1** — the conformance suite canon declared | found three stale `evaluate(self, account, marks)` fixtures that registered cleanly and would have failed at the first monitoring occurrence |
| `fd7541e` | **item 4** — `0.1.0a8` | verified the wheel actually carries `testing/` — it shipped as two 0-byte files before |
| `5449ad0` | **item 2, first half** — all four kinds register from the CLI | the old kind list contradicted canon §10.2; both new kinds register and appear in `list components` |

`577b39c`, `6224d53`, `d9031f8` are handoff updates. **`d9bd16a` is the user's own commit — untouched.**

Records: `docs/implementations/028`–`031`. New issue: `docs/issues/004`.

---

## Item 1 detail — what conformance is, and what it is not

`src/vqapr/testing/conformance/runner.py`, exported as `vqapr.public.conformance` **and**
`vqapr.testing.conformance` (canon requires reaching it without internal imports).

**It is a superset of the load door, never a copy.** `conformance()` calls the same `load_*` that
registration used to call, then checks what loading cannot see: every contract method is present,
callable, and declares the parameters Flow passes positionally. A load failure **rides through with
its own typed verdict** rather than being flattened.

`_register` no longer takes a `load=` callable — it calls `conformance(ref).raise_if_failed()`. One
implementation, three entrances, so a component cannot pass one and fail another.

**It deliberately does not judge behaviour.** Whether a callback returns a *useful* intent is only
knowable during a run. Widening it needs the fixture builders canon lists beside it
(`agendas.py`, `datasets.py`, `execution_tables.py`, `accounts.py`, `components.py`, `asserts.py`),
which are **not built** — that is why canon checklist line 4132 is still false.

---

## Open decisions — the user's, not yours

**`docs/issues/004`** — canon line 4129 wants `vqapr new`'s template to **fail** conformance;
`scaffold.py` decides a template must **run as written**. Measured: the scaffold passes. Both
intents are coherent and cannot both hold, and choosing decides what conformance *means*. My
recommendation is in the issue: withdraw 4129.

**`vqapr check` does not exist.** Canon line 4130 names three entrances; two now call the same code.
`cli/register.py` argues a separate `check` is unnecessary because registration already validates.
If that holds, 4130 should name two.

**Spec-shaping still raises bare `ValueError`/`TypeError`** — 7 sites in `cli/run.py`. Missing keys
are fixed, but a malformed *value* still reports `stage: "unhandled"`. Giving spec parsing its own
typed stage is a canon decision about the failure vocabulary. `FailureFamily` is a closed set of
package stages and spec parsing is in none of them.

**A1 — the testbed's `_project`/`_centre` vs `neutralize()`.** Sequential industry-demean-then-beta
and simultaneous regression differ when industry and beta are correlated. Which one the source
research used is a fact the user holds, and it **changes reproduction numbers**.

**Issues `002` and `003`** are already written with their reasoning; they need priority, not
analysis. `001` is Closed.

---

## How to verify anything here

```
uv run pytest -q                      # 594 passed
uv run ruff check src/ tests/         # clean
uv run python showcases/show_00N_*/run.py    # all eight run; 005 and 007 are the sharp ones
```

G-4 result invariance: `uv run python .agent/tmp/g4_check.py` compares show_005 against
`.agent/tmp/g4-snapshot/trace-baseline.json`. **Currently 64 fields identical.** Run show_005 first
— the check reads its `outputs/trace.json`.

> The baseline was re-cut earlier this session because it predated `c11d2e3` and had been failing on
> `recorder.defaults.account` (21 → 101) ever since — the documented widening from record 026, not a
> regression. It was re-cut from the committed tree *before* the B7 change, so its pass is real
> evidence rather than a reset.

**Two ruff gates, not one.** `ruff check src/ tests/` is the declared gate and is clean.
`ruff format --check` reports one pre-existing block in `weighting.py:155` that is also unformatted
on `HEAD~`. Left alone deliberately — it is nobody's change.

Probes from this session live in `.agent/tmp/` (untracked): `a3_cli_walk.py` walks the CLI as a
first-time user, `b8_probe.py` and `b8_mandatory_probe.py` document the execution-table findings.
