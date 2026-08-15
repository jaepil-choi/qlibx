from __future__ import annotations

from dataclasses import fields

from vqapr.models.contexts import DataModelContext


def test_datamodel_context_has_no_account_execution_or_workspace_surface() -> None:
    assert [item.name for item in fields(DataModelContext)] == ["window"]
    assert not hasattr(DataModelContext, "account")
    assert not hasattr(DataModelContext, "execution_input")
    assert not hasattr(DataModelContext, "workspace")
