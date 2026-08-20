"""The conformance suite every extension point passes, shipped to users.

Canon §10.3 ships this rather than keeping it in `tests/`, so a user can prove their own component
before registering it instead of reading our test suite to guess the contract.
"""

from __future__ import annotations

from vqapr.testing.conformance.runner import STAGE, conformance

__all__ = ["STAGE", "conformance"]
