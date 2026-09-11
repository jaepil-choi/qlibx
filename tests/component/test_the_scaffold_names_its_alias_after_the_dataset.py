"""`docs/issues/archive/063`: the scaffold's alias and docstring follow `--dataset` and `--field`.

`vqapr new strategy ou --dataset residuals --field resid` emitted `{"prices": read}`,
`call.read("prices", "resid")` and a docstring describing a long-only momentum ranker. The dataset
and the field went into the file; the alias and the description did not, so a first-time user read
`prices` as a required name and the docstring as a strategy they had not asked for.
"""

from __future__ import annotations

import ast

import pytest

from vqapr.component.reference import ComponentKind
from vqapr.component.scaffold import render


@pytest.mark.parametrize("kind", [ComponentKind.STRATEGY_MODEL, ComponentKind.DATA_MODEL])
def test_the_alias_is_the_dataset_id_and_the_docstring_names_the_read(kind: ComponentKind) -> None:
    source = render(kind, "ou-thresh", dataset_id="residuals", field="resid", lookback=30)

    assert '"prices"' not in source, "a fixed alias reads as a required name"
    module = ast.parse(source)
    klass = next(node for node in module.body if isinstance(node, ast.ClassDef))
    docstring = ast.get_docstring(klass) or ""
    assert "residuals" in docstring and "resid" in docstring, docstring
    assert "Ranks the cross-section" not in docstring
    assert "placeholder" in docstring, "the example signal is named as one, not as the strategy"

    assert '{"residuals": read}' in source
    if kind is ComponentKind.STRATEGY_MODEL:
        assert 'call.read("residuals", "resid")' in source
    else:
        assert 'context.read("residuals", FIELD)' in source


def test_the_rows_flavour_reads_the_same_alias() -> None:
    source = render(
        ComponentKind.DATA_MODEL,
        "per-name",
        dataset_id="vendor-long",
        field="px",
        lookback=5,
        lookback_kind="instants",
    )
    assert '{"vendor-long": read}' in source
    assert 'context.rows("vendor-long")' in source
    assert '"prices"' not in source
