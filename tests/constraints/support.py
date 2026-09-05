"""What a Constraint is handed, built for a test.

Every Constraint member now takes a `ConstraintCall` rather than a `ModelWindow` and a tuple
(record `129`+, `docs/issues/036`), so a test that used to pass `(window, instruments)` or
`(None, instruments)` passes one of these instead.

Two builders, because the two cases are genuinely different and collapsing them hides which one a
test is exercising:

- `reading_call` wraps a real `ModelWindow` and is what a constraint with declared `inputs()`
  needs. It is the production `ConstraintContext`, not a stand-in.
- `weightless_call` is for a rule that reads nothing -- `NoShort` is the shipped example -- and
  deliberately has no window at all. A test that hands it to a constraint which does read gets an
  `AttributeError` naming `read`, which is the honest failure: the test declared the rule reads
  nothing and the rule disagreed.
"""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.authoring import ConstraintCall
from vqapr.calls import ConstraintContext
from vqapr.data.windows import ModelWindow


def reading_call(window: ModelWindow, instruments: tuple[str, ...], constraint) -> ConstraintCall:
    """The production context, aliased by whatever the constraint declared."""
    return ConstraintContext(
        window=window, instruments=tuple(instruments), reads=constraint.inputs()
    )


@dataclass(frozen=True, slots=True)
class _Weightless(ConstraintCall):
    instruments: tuple[str, ...]

    @property
    def evaluation_time(self):
        raise AssertionError("a constraint that declares no reads has no evaluation time to use")

    def read(self, alias: str):
        raise AssertionError(f"this call serves no reads; {alias!r} was asked for")


    def rows(self, alias: str):
        raise TypeError("this double serves panel reads only")
def weightless_call(instruments: tuple[str, ...]) -> ConstraintCall:
    """A call for a rule that declared no `inputs()`. Reading through it is an error."""
    return _Weightless(tuple(instruments))
