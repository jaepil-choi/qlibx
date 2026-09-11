from __future__ import annotations

from dataclasses import fields

from vqapr.run.engine.calls import DataModelContext


def test_datamodel_context_has_no_account_execution_or_workspace_surface() -> None:
    """Capability ABSENCE is the subject; the field list is only evidence for it.

    The list read `["window"]` until record `128` added `reads`. That is not a new capability.
    `reads` holds the alias-keyed requirements the model declared in `inputs()`, and every one of
    them resolves *through* the window this context already carried — it narrows what the context
    will serve without widening what it can reach.

    What must stay absent is what a DataModel has no business seeing at all: an account, an
    execution input, a workspace handle. A DataModel computes values and values are not executed
    (§4.4), so none of the three has a reason to be here.
    """
    assert [item.name for item in fields(DataModelContext)] == ["window", "reads"]
    assert not hasattr(DataModelContext, "account")
    assert not hasattr(DataModelContext, "execution_table")
    assert not hasattr(DataModelContext, "workspace")
