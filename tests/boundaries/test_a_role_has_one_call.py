"""Every extension point is one callback that takes one Call and returns one judgment.

`test_the_layers_hold.py` says what may import what. This file says what the **shape** of an
extension point is (record `229`; the four kinds campaign's `203` wrote the rule first). The rule
the tree keeps:

> **A role takes one Call and returns one judgment. The Call is the whole of its authority.**

That second sentence is the load-bearing one. A `Call` is not a DTO -- it is a capability object,
and it is how point-in-time correctness is enforced by *inaccessibility* rather than by a rule
somebody has to remember (architecture 2.2, 10.1). What a role may reach is what its Call
exposes, so a new role answers "what can this see?" by naming one type, and a role that needs to
see more has to say so in a place a reader can find. Until `229` `Compliance.observe` took the
committed account beside its call, while the wiring table listed that account as a View the role
receives: the one place the table and a signature disagreed.

**Properties are not callbacks.** `compliance_id` and `Exchange.rules` are abstract too, and they
are identity and configuration rather than an invocation. The check below counts only abstract
members that are functions.

**What this does not check.** Whether the annotation is honest -- an annotation can lie, and
`component/conformance.py` is what checks the real object at registration, by arity, against the
call the run will actually make. This file checks the declared contract; that one checks the
component.
"""

from __future__ import annotations

import inspect

import pytest

from vqapr.authoring import (
    Compliance,
    ComplianceCall,
    Component,
    DataCall,
    DataModel,
    StrategyCall,
    StrategyModel,
)
from vqapr.component.exchange.base import Exchange, ExecutionCall
from vqapr.domain.wiring import WIRING, Role

ROLES: dict[type, tuple[str, type]] = {
    DataModel: ("compute", DataCall),
    StrategyModel: ("decide", StrategyCall),
    Compliance: ("observe", ComplianceCall),
    Exchange: ("execute", ExecutionCall),
}
"""Role -> (its one callback, the Call that callback receives).

Four, and `Exchange` is the one whose contract does not live in `authoring/`: it is handed an
`ExecutionCall`, whose vocabulary sits at layer 30, above the contract package at 20. The fifth
row of the wiring table, `ACCRUAL`, is a place with no class yet (design §7.3).
"""


def _callbacks(role: type) -> list[str]:
    """Abstract members of `role` that are functions -- properties are identity, not invocation."""
    return sorted(
        name
        for name in getattr(role, "__abstractmethods__", ())
        if inspect.isfunction(getattr(role, name, None))
    )


@pytest.mark.parametrize("role", list(ROLES), ids=lambda role: role.__name__)
def test_a_role_declares_exactly_one_callback(role: type) -> None:
    """Two callbacks on one role is what the two-clocks campaign removed (`Constraint`); one is
    what keeps it removed."""
    if role is Exchange:
        # A Protocol has no `__abstractmethods__`; its one callback is the one the loop calls.
        assert callable(getattr(Exchange, "execute", None))
        return
    assert _callbacks(role) == [ROLES[role][0]]


@pytest.mark.parametrize("role", list(ROLES), ids=lambda role: role.__name__)
def test_the_callback_takes_one_call_and_nothing_else(role: type) -> None:
    """`self` and the call. An argument beside the call is authority the Call does not describe."""
    name, call_type = ROLES[role]
    signature = inspect.signature(getattr(role, name))
    parameters = [p for p in signature.parameters.values() if p.name != "self"]

    assert len(parameters) == 1, (
        f"{role.__name__}.{name} takes {[p.name for p in parameters]}; a role's authority is its "
        f"Call, so anything it may reach belongs on {call_type.__name__} rather than beside it"
    )
    annotation = parameters[0].annotation
    assert annotation in (call_type, call_type.__name__), (
        f"{role.__name__}.{name} must receive a {call_type.__name__}; got {annotation!r}"
    )


@pytest.mark.parametrize("role", list(ROLES), ids=lambda role: role.__name__)
def test_the_callback_declares_what_it_returns(role: type) -> None:
    """One judgment, named. A role that returns `None` or nothing declared is not a contract."""
    name, _ = ROLES[role]
    annotation = inspect.signature(getattr(role, name)).return_annotation
    assert annotation is not inspect.Signature.empty, f"{role.__name__}.{name} declares no return"
    assert annotation not in (None, "None"), f"{role.__name__}.{name} returns nothing"


def test_every_authored_role_is_a_component_with_a_row() -> None:
    """One concept, one base (record `181`), and one row of the wiring table each (record `213`)."""
    for role in ROLES:
        if role is Exchange:
            continue
        assert issubclass(role, Component), role.__name__
        assert role.wiring() is WIRING[role.ROLE]


def test_the_compliance_call_carries_the_account_the_table_says_it_receives() -> None:
    """The table lists `COMMITTED_ACCOUNT` among what Compliance receives; the Call agrees."""
    from vqapr.domain.wiring import View

    assert View.COMMITTED_ACCOUNT in WIRING[Role.COMPLIANCE].receives
    assert "account" in ComplianceCall.__abstractmethods__


def test_the_four_roles_are_the_four_extension_points() -> None:
    """A fifth role added without a line here is a fifth thing a user can write that nothing says.

    Deliberately a count and a name set rather than a discovery sweep: adding a role is a decision
    somebody writes down, not something a test infers after the fact.
    """
    assert {role.__name__ for role in ROLES} == {
        "DataModel",
        "StrategyModel",
        "Compliance",
        "Exchange",
    }
