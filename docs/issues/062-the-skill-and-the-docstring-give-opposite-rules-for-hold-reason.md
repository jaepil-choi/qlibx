# 062 -- the skill and the docstring give opposite rules for `Hold(reason=...)`

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: the skill states the docstring's rule (prose, spaces allowed) and the scaffold's example reason has spaces.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-001**), against `vqapr-0.3.0`. Confirmed
against source the same day.

**Touches:** `src/vqapr/agent/skill/SKILL.md:429` (*"Return `Hold(reason="...")` to decline. The
reason is one token, no spaces."*); `src/vqapr/authoring.py:461-476` (`Hold`, whose docstring
says *"a reason a human reads should be allowed spaces"* and whose `__post_init__` only refuses an
empty string); the scaffold's `reason="no-name-scored-above-zero"`, hyphenated, which is
consistent with the stricter rule and so settles nothing.

## What happens

Two shipped documents on one wheel state opposite rules for one argument. The docstring is the
newer and the true one: record `125` merged `NoDecision` into `Hold` and deliberately kept the
looser validation. The skill line predates that and was not updated; the scaffold's hyphenated
example reads as a hedge.

## What to do

Delete the "one token, no spaces" sentence from the skill, or replace it with the docstring's
rule, and let the scaffold's example reason have a space in it so the example is the
documentation. The skill is generated from the package (`vqapr skill install`), so this is the
same class as `025` and `030`: a sentence in the skill that the code no longer backs.
