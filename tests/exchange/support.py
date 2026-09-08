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

from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.instruments import Instrument, InstrumentRoster
from vqapr.domain.orders import OrderBatch
from vqapr.exchange.execution_table import ExactExecutionSnapshot
from vqapr.exchange.venue import Exchange, ExecutionCall


def execution_call(
    venue: Exchange,
    orders: OrderBatch,
    account: AccountSnapshot,
    snapshot: ExactExecutionSnapshot,
    *,
    registry: InstrumentRoster | Mapping[str, Instrument] | None = None,
) -> ExecutionCall:
    """The call for `venue` at the snapshot's instant, its rules bound to `registry` if given."""
    rules = venue.rules if registry is None else venue.rules.with_registry(registry)
    return ExecutionCall(
        at=snapshot.target_at, orders=orders, account=account, snapshot=snapshot, rules=rules
    )
