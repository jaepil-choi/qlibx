"""What a Compliance rule is handed, built for a test.

Two builders, because the two cases are genuinely different and collapsing them hides which one a
test is exercising:

- `reading_call` wraps a real `ModelWindow` and is what a rule with declared `inputs()` needs. It
  is the production `ComplianceContext`, not a stand-in.
- `weightless_call` is for a rule that reads nothing -- `NoShort` is the shipped example -- and
  deliberately has no window at all. A test that hands it to a rule which does read gets an
  `AssertionError` naming `read`, which is the honest failure: the test declared the rule reads
  nothing and the rule disagreed.
"""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.authoring import ComplianceCall
from vqapr.authoring.context import ComplianceContext
from vqapr.data.windows import ModelWindow


def reading_call(window: ModelWindow, instruments: tuple[str, ...], rule) -> ComplianceCall:
    """The production context, aliased by whatever the rule declared."""
    return ComplianceContext(window=window, instruments=tuple(instruments), reads=rule.inputs())


@dataclass(frozen=True, slots=True)
class _Weightless(ComplianceCall):
    instruments: tuple[str, ...]

    @property
    def evaluation_time(self):
        raise AssertionError("a rule that declares no reads has no evaluation time to use")

    def read(self, alias: str, field: str):
        raise AssertionError(f"this call serves no reads; {alias!r} was asked for")

    def rows(self, alias: str):
        raise AssertionError(f"this call serves no reads; {alias!r} was asked for")


def weightless_call(instruments: tuple[str, ...]) -> ComplianceCall:
    """A call for a rule that declared no `inputs()`. Reading through it is an error."""
    return _Weightless(tuple(instruments))
