"""
Live-deploy account configuration
=================================

QMT broker-account dataclass shared by the portfolio runner and the QMT
client. The live-deploy config schema (slots, scheduling, calendar path,
risk overlay) lives in ``portfolio_deploy_config.py``.
"""

from dataclasses import dataclass


@dataclass
class QMTAccountConfig:
    """QMT account configuration."""
    qmt_path: str
    account_id: str
    account_type: str = "FUTURE"
