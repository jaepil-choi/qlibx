from qlibx import Project
from qlibx.research import ResearchCatalog, ResearchProposal
project = Project.load('.')
catalog = ResearchCatalog.from_project(project)
context = catalog.query_context(candidate={'mechanism': 'reversal'})
proposal = ResearchProposal(
    hypothesis='short-horizon reversal', mechanism='reversal',
    logical_datasets=('returns',), observation_clock='t-1 close',
    holding_horizon='5d', strategy='rolling_reversal', transforms=('rank',),
    parameter_range={'window': [3, 5, 10]},
    evaluation_segment={'start': '2025-01-01', 'end': '2025-03-31'},
    comparison_set=('baseline',), cost_assumptions={'bps': 10},
    capacity_assumptions={'participation': 0.1},
    stopping_condition='three failures', search_limit=3,
)
proposal_record = catalog.create_proposal(
    proposal, session_id='session-1', agent_id='agent-1'
)
