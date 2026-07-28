from qlibx import Project
from qlibx.ensemble import combine_stored_weights
from qlibx.research import ResearchCatalog
catalog = ResearchCatalog.from_project(Project.load('.'))
result = combine_stored_weights(
    catalog, members={'verified-record-id-a': 0.5, 'verified-record-id-b': 0.5}
)
# result.combined is ticker-level net intent; member strategies were not loaded.
