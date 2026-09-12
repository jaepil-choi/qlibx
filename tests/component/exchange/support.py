"""The `ExecutionCall` a venue test hands to `execute`.

This was `ExecutionCall.of`, a classmethod on the production type whose docstring called it
*"the call the handler builds"*. The handler does not build it: `ExecutionHandler` constructs
`ExecutionCall(...)` directly and binds the rules through its own `_bound_rules()`. Only tests
ever called `of`, so it is here, where its one caller is.

What it saves a test is the two derivations the handler also makes -- the instant comes from the
snapshot's target, and the venue's rules are bound to the project's roster when the test names
one. A test that wants to vary either builds `ExecutionCall` itself.
"""

from __future__ import annotations

from collections.abc import Mapping

from vqapr.component.exchange.base import Exchange, ExecutionCall
from vqapr.data.execution_table import ExactExecutionSnapshot
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.instrument import Instrument, InstrumentRoster
from vqapr.domain.order import OrderBatch


def execution_call(
    venue: Exchange,
    orders: OrderBatch,
    account: AccountSnapshot,
    snapshot: ExactExecutionSnapshot,
    *,
    registry: InstrumentRoster | Mapping[str, Instrument] | None = None,
) -> ExecutionCall:
    """The call for `venue` at the snapshot's instant, carrying `registry` as its dictionary.

    A test that bound the venue's own view beforehand (`venue._rules = ...with_registry(...)`)
    passes no registry, and the dictionary is read back off that view -- the call refuses a view
    bound to a different one.
    """
    rules = venue.rules
    if registry is None:
        instruments = rules.registry if rules.registry is not None else InstrumentRoster({})
    else:
        instruments = registry if isinstance(registry, InstrumentRoster) else InstrumentRoster(registry)
    return ExecutionCall(
        at=snapshot.target_at,
        orders=orders,
        account=account,
        snapshot=snapshot,
        instruments=instruments,
        rules=rules,
    )


class _WithRoster:
    """Delegates everything to the venue except `rules`, which serves the bound view."""

    def __init__(self, venue: Exchange, rules) -> None:
        self._venue = venue
        self._bound = rules

    @property
    def rules(self):
        return self._bound

    def execute(self, *args, **kwargs):
        return self._venue.execute(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._venue, name)


def bound(venue: Exchange, roster: InstrumentRoster | Mapping[str, Instrument]):
    """A venue whose view carries the project's dictionary, as the call binds it at a fill.

    Venues accept no roster of their own, so a test does what the Flow does: build the venue, then
    hand its view the identity it borrows (design §6.2: every ordered id is declared). The double
    delegates everything else to the venue, so `execute` is the profile's own.
    """
    return _WithRoster(venue, venue.rules.with_registry(roster))
