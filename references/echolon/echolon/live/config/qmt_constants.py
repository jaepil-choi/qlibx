"""miniQMT broker-status vocabulary.

Single source of truth for translating miniQMT's native ``xtconstant``
order-status integers (returned in callback objects and async responses)
into echolon-canonical status strings surfaced to strategies, the live
fill processor, and the LIV-002 / LIV-003 error catalog entries.

Add a new entry here whenever miniQMT ships a new status constant — both
``echolon.live.orchestrator.portfolio`` (live fill processing) and the
LIV-002 / LIV-003 documentation reference this table.
"""

from typing import Dict


# Mapping from miniQMT's xtconstant order-status integer to the
# echolon-canonical status vocabulary.
QMT_STATUS_MAP: Dict[int, str] = {
    48: "UNREPORTED",
    49: "WAIT_REPORTING",
    50: "SUBMITTED",
    53: "PARTIAL_CANCELED",
    54: "CANCELED",
    55: "PARTIAL_FILLED",
    56: "FILLED",
    57: "REJECTED",
}
