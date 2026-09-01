"""Names vulture reports as unused that are not.

Vulture reads names, not call graphs, so three shapes always misfire: a method the
interpreter or a framework calls by protocol, a class a registry resolves from a string,
and a dataclass field that is written at construction and read only by serialization.
Everything below is one of those three, with the caller named. Anything vulture reports
that is NOT in this file is a real finding and belongs in a deletion decision, not here.

Callers are named by symbol rather than by line number on purpose. The first version of
this file cited lines, and record 124's deletion moved or removed every one of them within
a day; a whitelist whose comments rot is worse than one that makes the reader grep.

Run:  uv run vulture
"""

# --- Protocol and framework call sites ------------------------------------------------
# Python itself calls this on a failed module attribute lookup.
__getattr__  # src/vqapr/__init__.py

# argparse calls its own `_print_message`; `_Parser` overrides it to write UTF-8 bytes so
# `--help` survives a cp949 console. Record 047.
_._print_message  # src/vqapr/cli/main.py


# --- Resolved from a string, invisible to a name-based pass ---------------------------
# `agent/sample/journey.py` registers this by the literal "SampleExchange".
SampleExchange  # src/vqapr/agent/sample/exchange.py


# --- Frozen dataclass fields: written at construction, read by serialization ----------
# src/vqapr/evidence/artifacts.py, class FailureObservation
exception_type
arguments

# src/vqapr/evidence/artifacts.py, class AccountCommitEvidence
planning_nav
planning_cash_target
planning_budget
intended_targets
requested_orders
account_version_before
account_version_committed

# src/vqapr/evidence/artifacts.py, class MarkEvidence
limitations

# src/vqapr/flow/simulation.py, class DueExecutionResult; built in `_execute_due`.
post_account_result


# --- pytest injects these by name, so no call site exists to find ---------------------
# Collection-time marker list applied to a whole module.
pytestmark

# `@pytest.fixture` definitions are covered by `ignore_decorators` in pyproject, but a test
# requesting one names it as a parameter, and that parameter has no reader in the body.
bound_every_source  # tests/flow/test_hot_path_costs.py
