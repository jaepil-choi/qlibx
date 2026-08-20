# 004 — Canon wants the scaffold to fail conformance; the scaffold is built to pass

**Status:** **Closed 2026-08-20.** Owner decided: the template must pass. Canon line 4129 was
withdrawn and the check it exposed was wrong in both directions — see record
`docs/implementations/032-arity-is-the-contract-not-spelling.md`.
Found 2026-08-20 while building the conformance suite (record 031).
**Touches:** `docs/vqapr-architecture.md` line 4129, `src/vqapr/extension/scaffold.py`,
`src/vqapr/testing/conformance/runner.py`

## The contradiction

Canon's §16 checklist asks for:

> - [ ] `vqapr new`가 깐 템플릿이 **처음에는 conformance를 통과하지 못한다**

`scaffold.py` decides the opposite, in its module docstring:

> A template must **run as written**. A skeleton that raises on the first callback teaches nothing
> and cannot be executed to see the shape of a result, so the emitted file is a complete working
> Strategy with exactly one marked place to change.

Measured against the suite shipped in record 031, the scaffold decision is the one that holds:

```
strategy_model   scaffold passes conformance? True
data_model       scaffold passes conformance? True
```

## Which is right depends on what conformance is for

Both intents are coherent; they just cannot both be true.

**"Fail first" makes conformance a to-do list.** The generated file carries a deliberate hole, the
suite names it, and the user knows they are not done. This is the `# ---- the one line to change`
marker turned into an executable check.

**"Run as written" makes conformance a contract check.** The template is a working example, and
the suite answers only *"can Flow call this?"* — which is what record 031 built, and what
registration now enforces. Under this reading a scaffold that failed its own suite would mean the
package ships a broken example.

They can be reconciled — a suite could separate *"the contract is satisfiable"* from *"the marked
decision has been made"* — but that is a second verdict with its own vocabulary, and inventing it
silently would put two meanings behind one word.

## Recommendation

Withdraw line 4129, keep `scaffold.py` as it is. A package whose own generated template fails its
own suite teaches the wrong thing on the first command a user types, and the "not done yet" signal
already exists in the source as the marked line.

Withdrawal is not free: the checklist item is the only place canon states that a fresh template is
incomplete. If it goes, `vqapr new`'s output should say so in its docstring instead.

## Also unresolved on the same checklist

**`vqapr check` does not exist.** Line 4130 asks that *"`pytest` · `vqapr check` · `vqapr register`
call the same conformance code"*. Two of the three now do — `register` calls `conformance()` and
tests call it directly. There is no `check` command, so the third is unbuilt rather than wrong;
`cli/register.py` argues it is unnecessary because registration already validates. If that argument
holds, line 4130 should name two entrances rather than three.

**Line 4132 is still false.** *"사용자가 `vqapr.testing`만으로 자기 StrategyModel을 실행해볼 수 있다"*
needs the fixture builders canon §10.3 lists beside the suite — `agendas.py`, `datasets.py`,
`execution_tables.py`, `accounts.py`, `components.py`, `asserts.py`. Record 031 shipped the suite
only. Running a Strategy needs a context, and a context needs those builders.

---

## Resolution (2026-08-20)

**Owner decision: canon was wrong. The template must pass conformance — "do nothing" is enough.**

Conformance means *"the component returns the expected output type"*. Little of that is decidable
before a run, so a template that returns a valid `NoDecision` is conformant and canon line 4129 is
withdrawn.

Measuring the suite against that definition found it was answering neither question correctly:

```
component     conformance            Flow can call it?
do_nothing    PASS                   yes -> NoDecision      correct
renamed       FAIL signature_invalid yes -> NoDecision      FALSE POSITIVE
wrong_arity   FAIL signature_invalid NO (TypeError)         correct, by accident
wrong_return  PASS                   yes -> dict            FALSE NEGATIVE
```

It refused working code and accepted the exact mistake the definition names. The same
name-comparison also existed a second time in `extension/loading.py`, so the two entrances canon
requires to agree were two independent implementations.

Resolved by making arity the contract, defining it once in `loading.py`, and letting the Flow judge
the returned value at the call site where it exists. `vqapr check` is **not** built: `register`
already calls `conformance()`, and the return-type question is runtime-only. Canon line 4130 now
names two entrances.

`tests/extension/test_all_four_doors.py::test_the_scaffold_registers_as_written` keeps canon and
`scaffold.py` from drifting apart again.

## Still open from this file, moved out of scope

Line 4132 (*"사용자가 `vqapr.testing`만으로 자기 StrategyModel을 실행해볼 수 있다"*) is still false and needs
the fixture builders canon §10.3 lists — `agendas.py`, `datasets.py`, `execution_tables.py`,
`accounts.py`, `components.py`, `asserts.py`. That is a separate build, not part of this decision.
