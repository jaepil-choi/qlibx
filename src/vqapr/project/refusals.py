"""One refusal, one failure, for everything the project layer declines.

`_workspace_error` and its twenty-six callers lived in one file until record `194`, and a test
pinned them there: an attempt to move it measured **37 refusal codes removed from the baseline**
with a green suite and a clean lint, because the inventory that resolves a forwarded `code`
argument could only follow a helper defined in the same file.

Record `171` rebuilt that inventory package-wide -- its `_SourceIndex` is *"built once over every
module under `src/vqapr`"*, and says in as many words that the per-file version *"dropped codes
from the baseline"* whenever a module was split. The constraint expired with it, and the campaign
measured that before moving anything: the constructor moved to a probe module, its callers stayed,
and the gate reported gained 0 / lost 0 with all 22 literal codes still resolved
(`docs/refactoring/2026-09-08-the-layering-campaign.md` section 5).

So it lives here, where `store.py`, `merge.py` and `references.py` can all reach it without one of
them owning the other.
"""

from __future__ import annotations

from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError


def _workspace_error(
    *,
    stage: Stage,
    code: str,
    status: Status,
    requirement: str,
    observed: str,
    retry: str,
    fix: str,
    source: FailureSource | None = None,
    cause: BaseException | None = None,
) -> VqaprError:
    """One refusal, one failure. `cause` is the exception in hand at the site, when there is one;
    otherwise the failure records the site itself (record `171`)."""
    return VqaprError(
        stage=stage,
        failures=[
            Failure.bounded(
                code,
                requirement,
                status=status,
                observed=observed,
                fix=fix,
                source=source,
                cause=cause,
            )
        ],
        mutation=False,
        retry_precondition=retry,
    )
