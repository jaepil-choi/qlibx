# Handoff — conformance decided, and the CLI declaration surface closed

Status: in_progress
Branch: `jaepil-develop` · last commit `469de4e` · **tree is green: 609 passed, ruff clean**
**Nothing is uncommitted.** Version is `0.1.0a8`.

Supersedes `2026-08-20-testbed-gap-closure.md`, which is fully closed.

The user asked for items **1 → 4 → 2** from a decision list. **All four are done.** Items 1 and 4
landed earlier; this session closed the two conformance decisions and finished item 2.

---

## Resume here: the decisions the user still owns

Three of the five open questions from the previous handoff are now closed. **These remain, and
they are the user's, not yours.**

**A1 — the testbed's `_project`/`_centre` vs `neutralize()`.** Sequential industry-demean-then-beta
and simultaneous regression differ when industry and beta are correlated. Which one the source
research used is a fact the user holds, and it **changes reproduction numbers**. This is the one
that blocks reproduction work; ask it first.

**Issues `002` and `003`** are written with their reasoning; they need priority, not analysis.
`003` (a cost band cannot name an instrument) is the sharper one — KRX exempts ETFs from the
securities transaction tax, and charging a sleeve 23bp instead of 3bp is **0.20–0.40pp a year**,
which is 14–27% of the +1.47% net excess being reproduced. `001` and `004` are Closed.

**Spec-shaping still raises bare `ValueError`/`TypeError`** — 7 sites in `cli/run.py`, and
`cli/declare.py` now adds its own. Missing keys are named, but a malformed *value* still reports
`stage: "unhandled"`. Giving spec parsing a typed stage is a canon decision about the failure
vocabulary: `FailureFamily` is a closed set of package stages and spec parsing is in none of them.
This is now the largest remaining rough edge on the CLI surface.

---

## Closed this session

### Conformance: the template passes, and `vqapr check` will not be built

The user decided canon was wrong. Conformance means *"the component returns the expected output
type"*, and little of that is decidable before a run, so a do-nothing template is conformant.

Measuring the suite against that definition found it was **backwards in both directions**:

```
component     conformance            Flow can call it?
do_nothing    PASS                   yes -> NoDecision      correct
renamed       FAIL signature_invalid yes -> NoDecision      FALSE POSITIVE
wrong_arity   FAIL signature_invalid NO (TypeError)         correct, by accident
wrong_return  PASS                   yes -> dict            FALSE NEGATIVE
```

It refused a renamed parameter (`ctx` instead of `context`) that Flow calls identically, and
accepted the exact mistake the user's definition names. **The same name comparison also existed a
second time in `extension/loading.py`** — so the two entrances canon requires to agree were two
independent implementations, which is the state canon forbids.

Arity is now the contract, defined once in `loading.py` (`positional_arity`,
`accepts_contract_call`) and imported by the suite. The returned *value* is judged where it exists:
`validate_economic_intent`, `_validated_output`, and `Constraint.project`'s isinstance gate.

`vqapr check` is **not** built and canon now names two entrances, not three: `register` already
calls `conformance()`, and the remaining question is runtime-only.

### The CLI surface: one door, `register`

The user rejected the two-verb split record 033 shipped, on the right grounds — *"register가 애초에
필요한 yaml을 같이 요구해야 하는거고 그게 없으면 아예 register를 거부해야 해."* That is what canon
§10.2 already drew.

```
vqapr register <declaration.yaml>     # 7 sections: datasets, execution_inputs, agendas,
                                      #   components, strategy_configs, valuation_configs,
                                      #   monitoring_policies
vqapr new strategy my-alpha --dataset prices   # emits my_alpha.py AND my_alpha.yaml
vqapr run <spec.yaml>
vqapr list <kind>
```

`declare` is deleted. **A component cannot be registered from argv alone** without registering
something no run can use — no dataset it reads, no cadence it runs on. So the unit of registration
is the declaration file, and `new` emits one beside what it scaffolds. Record `034`.

Verified as a first-time user types it, no library import anywhere: empty directory →
`register workspace.yaml` → `new strategy` → `register my_alpha.yaml` → `register rest.yaml` →
`run spec.yaml` → `occurrences=9, account_version=9`.

The PK validation the user asked about **already existed and is now reachable**: a duplicated
`(available_at, instrument)` is refused with the offending group as evidence and nothing written.

### Superseded: item 2's first shape

`vqapr declare <file.yaml>` covers all seven declarations that had no CLI path — datasets (with
their sources), execution inputs, agendas, and the three configs. One command taking one file
rather than seven taking flags, because `register` means *"fingerprint this code"* and none of the
seven has code, and because they reference each other and would otherwise be ordered by trial.

`_workspace_for_run` in `tests/cli/test_commands.py` now builds the entire workspace through
`main(argv)`. **Removing the library imports it no longer needed deleted 18 imports** — that is the
measure of the gap that existed.

| commit | what |
|---|---|
| `a6af89d` | arity is the contract, not spelling — record `032`, issue `004` closed |
| `e2cdbb0` | the seven declarations reached a CLI path — record `033` (shape superseded) |
| `469de4e` | `register` is the one door; `declare` deleted — record `034` |

---

## How to verify anything here

```
uv run pytest -q                      # 609 passed
uv run ruff check src/ tests/         # clean
uv run python showcases/show_00N_*/run.py    # all eight run; 005 and 007 are the sharp ones
```

G-4 result invariance: `uv run python .agent/tmp/g4_check.py` compares show_005 against
`.agent/tmp/g4-snapshot/trace-baseline.json`. **Verified this session: 64 fields identical**,
final NAV `1168064370.53000000`, 62 dealt fills. Run show_005 first — the check reads its
`outputs/trace.json`. Neither change this session moved a number.

**Two ruff gates, not one.** `ruff check src/ tests/` is the declared gate and is clean.
`ruff format --check` reports one pre-existing block in `weighting.py:155` that is also unformatted
on `HEAD~`. Left alone deliberately — it is nobody's change.

Probes in `.agent/tmp/` (untracked): `conformance_value_probe.py` produces the four-row table
above and is the fastest way to re-measure that the check still points the right way.
`a3_cli_walk.py` walks the CLI as a first-time user.

---

## What is still unbuilt, with its reason

**Canon line 4132 is still false.** *"사용자가 `vqapr.testing`만으로 자기 StrategyModel을 실행해볼
수 있다"* needs the fixture builders canon §10.3 lists beside the suite — `agendas.py`,
`datasets.py`, `execution_tables.py`, `accounts.py`, `components.py`, `asserts.py`. Records 031 and
032 shipped the suite and made its verdict correct; running a Strategy needs a context, and a
context needs those builders. This is the natural next build and it is now the only thing standing
between a user and testing their own component without a workspace.

**`register` cannot remove a declaration.** Removing one is not reachable from the CLI.

**`.vqapr/workspace.yaml` is an unguarded output.** The user raised tamper-detection — a digest the
system remembers so a hand-edit invalidates the workspace — then judged the responsibility not
obviously worth it, and nothing was built. Nothing currently says the file must not be hand-edited,
which is the cheap half of that decision if it is ever wanted.

**A flake to watch, not caused by this work.** `tests/test_workspace_concurrency.py::
test_parallel_registrations_all_survive` failed once with `workspace.open.unreadable` during a full
run, then passed 6/6 in isolation on the stashed tree and 3/3 in full runs afterwards. It touches no
CLI code. If it recurs, it is a real cross-process read race and not a test artefact.
