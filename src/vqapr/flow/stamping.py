"""Package-owned availability rules for derived observation rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from vqapr.data.windows import AccessRecord
from vqapr.domain.timestamps import require_tz_aware


def derived_available_at(
    evaluation_time: datetime,
    accesses: Sequence[AccessRecord],
) -> datetime:
    """Stamp when a derived value was knowable from the rows actually consumed."""
    stamped = require_tz_aware(evaluation_time, name="evaluation_time")
    for access in accesses:
        observed = access.max_available_at
        if observed is not None and observed > stamped:
            stamped = observed
    return stamped
