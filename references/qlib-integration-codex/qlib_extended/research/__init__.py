"""Systematic alpha research infrastructure."""

from qlib_extended.research.catalog import (
    DataCatalog,
    DatasetSpec,
    ParquetSourceSpec,
)
from qlib_extended.research.loader import ConfigDrivenDataLoader
from qlib_extended.research.legacy import LegacyImportSummary, LegacyResearchImporter
from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.alpha import AlphaDefinition, load_alpha_definitions
from qlib_extended.research.costs import (
    AsymmetricCostContract,
    cross_member_targets,
)
from qlib_extended.research.consensus import (
    ConsensusHybridInputs,
    ConsensusHybridSpec,
    ConsensusHybridSummary,
    build_consensus_hybrid_specs,
    execute_consensus_hybrid_search,
    load_consensus_hybrid_inputs,
    prepare_consensus_hybrid_scores,
)
from qlib_extended.research.cohorts import (
    ConsensusCohortSummary,
    publish_consensus_calendar_cohorts,
)
from qlib_extended.research.evaluation import (
    ForwardFreeze,
    WalkForwardFold,
    WalkForwardScheme,
    evaluate_walk_forward_returns,
    rank_walk_forward_candidates,
)
from qlib_extended.research.dynamic_ensemble import (
    DynamicAllocationSpec,
    allocation_turnover,
    build_causal_allocation,
    combine_targets,
)
from qlib_extended.research.financial import (
    FinancialShadowSummary,
    publish_financial_shadow_outputs,
)
from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec
from qlib_extended.research.market import (
    MarketCohortContract,
    MarketCohortSummary,
    load_market_cohort_contract,
    publish_market_calendar_cohorts,
)
from qlib_extended.research.leaderboard import (
    LeaderboardBuildResult,
    LeaderboardConfig,
    build_leaderboards,
    load_historical_medals,
    rank_eligible_candidates,
    render_eligible_markdown,
    render_historical_markdown,
)
from qlib_extended.research.pool import AlphaPoolCatalog, rebuild_catalog
from qlib_extended.research.portfolio import (
    benchmark_scale_active_target,
    FamilyAllocation,
    PhysicalPortfolioConfig,
    PhysicalSearchSummary,
    PhysicalTrialSpec,
    execute_physical_portfolio_search,
    project_benchmark_neutral,
    project_direct_stock,
    simulate_physical_portfolio,
)

__all__ = [
    "ConfigDrivenDataLoader",
    "ConsensusHybridInputs",
    "ConsensusHybridSpec",
    "ConsensusHybridSummary",
    "ConsensusCohortSummary",
    "AlphaDefinition",
    "AsymmetricCostContract",
    "DataCatalog",
    "DatasetSpec",
    "DynamicAllocationSpec",
    "ImmutableArtifactStore",
    "ForwardFreeze",
    "FinancialShadowSummary",
    "FamilyAllocation",
    "LegacyImportSummary",
    "LegacyResearchImporter",
    "LeaderboardBuildResult",
    "LeaderboardConfig",
    "MemberWeight",
    "MetricValue",
    "MarketCohortContract",
    "MarketCohortSummary",
    "ParquetSourceSpec",
    "PhysicalPortfolioConfig",
    "PhysicalSearchSummary",
    "PhysicalTrialSpec",
    "RunSpec",
    "WalkForwardFold",
    "WalkForwardScheme",
    "AlphaPoolCatalog",
    "cross_member_targets",
    "allocation_turnover",
    "build_consensus_hybrid_specs",
    "build_leaderboards",
    "benchmark_scale_active_target",
    "build_causal_allocation",
    "combine_targets",
    "evaluate_walk_forward_returns",
    "execute_consensus_hybrid_search",
    "execute_physical_portfolio_search",
    "rank_walk_forward_candidates",
    "rank_eligible_candidates",
    "load_alpha_definitions",
    "load_consensus_hybrid_inputs",
    "load_historical_medals",
    "load_market_cohort_contract",
    "prepare_consensus_hybrid_scores",
    "publish_financial_shadow_outputs",
    "publish_consensus_calendar_cohorts",
    "publish_market_calendar_cohorts",
    "project_benchmark_neutral",
    "project_direct_stock",
    "rebuild_catalog",
    "render_eligible_markdown",
    "render_historical_markdown",
    "simulate_physical_portfolio",
]
