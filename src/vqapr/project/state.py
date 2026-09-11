"""Everything `workspace.yaml` holds, as one value.

Its own module because three others need it and none of them should have to import the class that
happens to hold one: `merge.py` folds a declaration into a state, `references.py` searches one, and
`store.py` reads and writes them. A `_State` in `store.py` would make both of the first two import
the `Workspace` module to name their own argument type.
"""

from __future__ import annotations

from typing import NamedTuple

from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.domain.identifiers import ComponentId, DatasetId, SourceId
from vqapr.extension.component import ComponentRef
from vqapr.project.run import RunDefinition


class _State(NamedTuple):
    """Everything `workspace.yaml` holds, as one value.

    A tuple, so every `*state` unpacking in this module still works; named,
    so a merge can say `state.agendas` and `state._replace(agendas=...)` instead of threading
    eight positional mappings through every signature. What it encodes is unchanged.
    """

    datasets: dict[DatasetId, DatasetRegistration]
    sources: dict[SourceId, SourceSpec]
    components: dict[ComponentId, ComponentRef]
    runs: dict[str, RunDefinition]
    """Registered runs (record `139`): the reusable configuration `vqapr run <run-id>` executes."""
