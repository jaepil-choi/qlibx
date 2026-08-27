"""Package-owned availability rules for derived observation rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from vqapr.data.windows import AccessRecord
from vqapr.domain.timestamps import require_tz_aware


class LookAheadDetected(AssertionError):
    """A read returned a row that was not knowable at the instant that read it.

    Its own exception type because this is not a bug in the caller's declaration -- it is the
    package having violated its own point-in-time boundary, and the two want different responses.
    """


def derived_available_at(
    evaluation_time: datetime,
    accesses: Sequence[AccessRecord],
) -> datetime:
    """Stamp when a derived value was knowable from the rows actually consumed.

    The answer is always `evaluation_time`, and the loop that used to search for a later instant
    was unreachable. It was unreachable *contingently*, not by construction: `scan.py:579,620` bind
    every observation query with `WHERE available_at <= evaluation_time`, so no access can carry a
    later one. Loosen that bound and the loop becomes live again.

    Deleting it would have satisfied the dead-code rule and quietly removed the only thing watching
    for the failure. That failure is uniquely dangerous here because look-ahead **improves**
    correlations: a leak makes every downstream number look better, so neither the count gate nor
    `compare_factors.py` would flag it, and nothing else in the stack is looking. A silent
    improvement is the hardest kind of wrong to notice.

    So the branch is gone and the invariant it depended on is now checked instead. It costs one
    comparison per access on a path that already iterates them, and it fails loudly the moment the
    PIT bound stops holding.
    """
    stamped = require_tz_aware(evaluation_time, name="evaluation_time")
    for access in accesses:
        observed = access.max_available_at
        if observed is not None and observed > stamped:
            raise LookAheadDetected(
                "a read returned a row newer than the instant that read it: "
                f"{getattr(access, 'dataset_id', '<unknown dataset>')} carried "
                f"{observed.isoformat()} at evaluation_time {stamped.isoformat()}. "
                "Every observation query binds available_at <= evaluation_time "
                "(scan.py:579,620); reaching this means that bound was loosened, and "
                "look-ahead improves correlations rather than breaking them, so no downstream "
                "gate would have caught it."
            )
    return stamped
